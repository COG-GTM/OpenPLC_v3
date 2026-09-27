"""Alarm-List-L4-WASH-01.csv - every row of the alarm list against the compiled program.

The CSV is the import for the Ignition alarm journal (FDS section 7), so it is read here
as the source of truth: bit / value, priority, machine response, latched, clears.
"""
import csv
from pathlib import Path

import pytest

import openplc_sil as sil

ALARM_LIST = Path(__file__).resolve().parent.parent / "docs" / "Alarm-List-L4-WASH-01.csv"

with ALARM_LIST.open(newline="") as _fh:
    ROWS = list(csv.DictReader(_fh))

OPEN_LOOP = -32768


def to_washing(plc):
    """seq 10 -> part in chamber, pump proven, spray timer running (as conftest.washing)."""
    plc.set("PE_INFEED", True)
    plc.scan(2)
    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    assert plc.seq() == 30
    plc.follow_pump_aux()
    plc.scan(2)
    assert plc.get("PUMP_RUN")


def heater_on_at_temp(plc):
    """Bring the tank up through the band so the heater is ON while TEMP_AT_SP holds."""
    plc.set_temp_c(52.0)
    plc.scan(2)
    plc.set_temp_c(54.0)
    plc.scan(2)
    assert plc.get("HEATER_ON")


def settle(plc):
    plc.scan(2)
    plc.follow_pump_aux()
    plc.scan(1)


# tag -> (trigger, clear_cause); each starts from the in_cycle fixture (EXECUTE, seq 10)
def _estop(plc):
    to_washing(plc)
    plc.set("ESTOP_OK", False)
    settle(plc)


def _guard(plc):
    to_washing(plc)
    plc.set("GUARD_CLOSED", False)
    settle(plc)


def _tank_low(plc):
    to_washing(plc)
    plc.set("LSL_TANK", False)
    settle(plc)


def _tank_high(plc):
    to_washing(plc)
    plc.set("LSH_TANK", True)
    settle(plc)


def _temp_low(plc):
    to_washing(plc)
    plc.set_temp_c(30.0)         # < SP - 2 x hyst = 51 degC
    settle(plc)


def _temp_high(plc):
    to_washing(plc)
    plc.set_temp_c(66.0)         # > SP + 10
    settle(plc)


def _jam(plc):
    plc.set("SP_JAM_TIME_S", 2)
    plc.set("PE_INFEED", True)
    plc.scan(2)
    assert plc.seq() == 20 and plc.get("INFEED_RUN")
    plc.run(seconds=2.5)


def _pump_fts(plc):
    to_washing(plc)
    plc.set("PUMP_AUX", False)   # contactor drops while commanded
    plc.run(seconds=3.5)


def _pump_ol(plc):
    to_washing(plc)
    plc.set("PUMP_OL_OK", False)
    settle(plc)


def _vfd(plc):
    to_washing(plc)
    plc.set("INFEED_VFD_RDY", False)
    settle(plc)


def _lt_fail(plc):
    plc.set("SP_FILL_PCT_X10", 900)   # valve open at 80 % so "fill valve closed" is observable
    plc.scan(2)
    assert plc.get("FILL_VALVE")
    to_washing(plc)
    plc.set("TANK_LEVEL_RAW", OPEN_LOOP)
    settle(plc)


def _tt_fail(plc):
    heater_on_at_temp(plc)
    to_washing(plc)
    plc.set("TANK_TEMP_RAW", OPEN_LOOP)
    settle(plc)


def _blocked(plc):
    plc.set("SP_WASH_TIME_S", 2)
    plc.set("SP_BLOCKED_WARN_S", 3)
    to_washing(plc)
    plc.set("PE_OUTFEED", True)
    plc.run(seconds=3)
    assert plc.seq() == 40
    plc.follow_pump_aux()
    plc.run(seconds=3.5)


def _htr(plc):
    heater_on_at_temp(plc)
    to_washing(plc)
    plc.set("HTR_OK", False)
    settle(plc)


TRIGGER = {
    "A_ESTOP": (_estop, lambda p: p.set("ESTOP_OK", True)),
    "A_GUARD_OPEN": (_guard, lambda p: p.set("GUARD_CLOSED", True)),
    "A_TANK_LOW": (_tank_low, lambda p: p.set("LSL_TANK", True)),
    "A_TANK_HIGH": (_tank_high, lambda p: p.set("LSH_TANK", False)),
    "A_TEMP_LOW": (_temp_low, lambda p: p.set_temp_c(55.0)),
    "A_TEMP_HIGH": (_temp_high, lambda p: p.set_temp_c(55.0)),
    "A_JAM": (_jam, lambda p: p.set("PE_INFEED", False)),
    "A_PUMP_FTS": (_pump_fts, lambda p: None),
    "A_PUMP_OL": (_pump_ol, lambda p: p.set("PUMP_OL_OK", True)),
    "A_VFD_FAULT": (_vfd, lambda p: p.set("INFEED_VFD_RDY", True)),
    "A_LT_FAIL": (_lt_fail, lambda p: p.set_level_pct(80.0)),
    "A_TT_FAIL": (_tt_fail, lambda p: p.set_temp_c(54.0)),
    "A_BLOCKED": (_blocked, lambda p: p.set_many(PE_OUTFEED=False, PE_CHAMBER=False)),
    "A_HTR_HILIMIT": (_htr, lambda p: p.set("HTR_OK", True)),
}


def test_fds_alm_bit_values_match_alarm_list():
    """Alarm list columns Bit / Value: 'Value' is 2^Bit, bits 0..13 are each used exactly
    once, and the harness's ALM map (used by every other test) agrees with the CSV."""
    assert [int(r["Bit"]) for r in ROWS] == list(range(14))
    for row in ROWS:
        bit, value = int(row["Bit"]), int(row["Value"])
        assert value == 1 << bit, row["Alarm Tag"]
        assert sil.ALM[row["Alarm Tag"][2:]] == bit, row["Alarm Tag"]
    assert set(TRIGGER) == {r["Alarm Tag"] for r in ROWS}


@pytest.mark.parametrize("row", ROWS, ids=[r["Alarm Tag"] for r in ROWS])
def test_fds_alm_row(in_cycle, row):
    """Alarm list row: 'Trigger' sets exactly this row's bit in HMI_ALARMS; 'Priority'
    drives red+horn (Critical) or amber (Warning); 'Machine Response' ABORT / HOLD / None
    is the PackML state reached; 'Latched' decides whether removing the cause clears the
    bit or RESET is needed; 'Clears' returns the machine to IDLE (STOPPED after an abort)."""
    plc = in_cycle
    tag, bit, value = row["Alarm Tag"], int(row["Bit"]), int(row["Value"])
    response, priority = row["Machine Response"], row["Priority (ISA-18.2)"]
    latched = row["Latched"].startswith("Yes")
    trigger, clear_cause = TRIGGER[tag]

    trigger(plc)
    assert plc.get("HMI_ALARMS") == value, f"{tag}: expected only bit {bit}"
    assert plc.alarm(bit)

    if "ABORT" in response:
        expected_state = sil.ABORTED
    elif "HOLD" in response:
        expected_state = sil.HELD
    else:
        expected_state = sil.EXECUTE
    assert plc.state() == expected_state, f"{tag}: {response}"
    if expected_state != sil.EXECUTE:
        assert not plc.get("PUMP_RUN") and not plc.get("INFEED_RUN")
    if "Heaters off" in response:
        assert not plc.get("HEATER_ON"), tag
    if "fill valve opens" in response.lower():
        assert plc.get("FILL_VALVE"), tag
    if "fill valve closed" in response.lower():
        assert not plc.get("FILL_VALVE"), tag

    if priority == "Critical":
        assert plc.get("STACK_RED") and plc.get("HORN"), tag
    else:
        assert priority == "Warning"
        assert plc.get("STACK_AMBER") and not plc.get("STACK_RED") and not plc.get("HORN"), tag

    clear_cause(plc)
    settle(plc)
    if latched:
        assert plc.alarm(bit), f"{tag} is latched: removing the cause must not clear it"
        plc.pulse("PB_RESET")
    assert not plc.alarm(bit), f"{tag}: not cleared ({row['Clears']})"
    if expected_state == sil.EXECUTE:
        assert plc.state() == sil.EXECUTE
    else:
        if not latched:
            assert plc.state() == expected_state, "cause gone, still waiting for RESET"
            plc.pulse("PB_RESET")
        assert plc.state() == (sil.STOPPED if expected_state == sil.ABORTED else sil.IDLE), tag
    assert plc.get("HMI_ALARMS") == 0
    assert not plc.get("HORN")
