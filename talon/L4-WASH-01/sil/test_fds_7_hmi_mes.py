"""FDS-L4-WASH-01 section 7 - HMI / MES registers, setpoints, Modbus map, stack light."""
import csv
from pathlib import Path

import openplc_sil as sil

IO_LIST = Path(__file__).resolve().parent.parent / "docs" / "IO-List-L4-WASH-01.csv"
HMI_REGS = ("HMI_STATE", "HMI_STEP", "HMI_ALARMS", "HMI_TANK_TEMP",
            "HMI_TANK_LEVEL", "HMI_PUMP_PRESS", "HMI_CYCLE_COUNT", "HMI_WASH_REMAIN")


def io_rows():
    with IO_LIST.open(newline="") as fh:
        return list(csv.DictReader(fh))


def modbus_ref(loc: sil.Location) -> str:
    """Runtime's fixed Modbus map: %IX -> DI, %QX -> Coil, %IW -> IR, %QW -> HR 0.., %MW -> HR 1024.."""
    if loc.size == "X":
        n = loc.byte * 8 + loc.bit
        return f"DI {n}" if loc.area == "I" else f"Coil {n}"
    if loc.area == "I":
        return f"IR {loc.byte}"
    return f"HR {loc.byte}" if loc.area == "Q" else f"HR {1024 + loc.byte}"


def test_fds_7_tag_addresses_match_io_list():
    """FDS section 2: 'Full tag/terminal list: IO-List-L4-WASH-01.csv'; section 7: 'Holding
    registers 0-7 (%QW0..7)', setpoints 'HR 1024..1029'. Every located variable in the
    program is in the IO list at the same address and Modbus reference, and vice versa."""
    rows = {r["Tag"]: r for r in io_rows()}
    tags = sil.parse_tag_map()
    assert set(tags) == set(rows)
    for tag, loc in tags.items():
        assert rows[tag]["Address"] == loc.address, tag
        assert rows[tag]["Type"] == loc.type, tag
        assert rows[tag]["Modbus (slave addr)"] == modbus_ref(loc), tag


def test_fds_7_setpoint_defaults_match_io_list(plc):
    """FDS section 5: 'Setpoints are supervisor-level HMI writes to %MW0..5; defaults are in
    the IO list.' IO list HR1024-1029: default 550 / 20 / 90 / 8 / 650 / 60."""
    setpoints = [r for r in io_rows() if r["Signal"] == "setpoint"]
    assert len(setpoints) == 6
    for row in setpoints:
        default = int(row["Fail State / Note"].split("default")[1].split(";")[0])
        assert plc.get(row["Tag"]) == default, row["Tag"]
    plc.run(seconds=5)
    assert plc.get("SP_TEMP_X10") == 550, "program never writes the setpoint registers"


def test_fds_7_status_registers_hr0_to_hr7(in_cycle):
    """FDS section 7: 'Holding registers 0-7 (%QW0..7) are polled by the Ignition gateway
    every 1 s.' IO list HR0-7: State, Step, AlarmWord, TankTemp degC x10, TankLevel % x10,
    SprayPress bar x100, CycleCount, WashRemain seconds."""
    plc = in_cycle
    plc.set("SP_WASH_TIME_S", 40)
    plc.set_temp_c(56.3)
    plc.set_level_pct(72.5)
    plc.set_press_bar(0.0)
    plc.scan(2)
    regs = lambda: [plc.get(t) for t in HMI_REGS]
    assert regs() == [sil.EXECUTE, 10, 0, 563, 725, 0, 0, 0]

    plc.set("PE_INFEED", True)
    plc.scan(2)
    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    assert regs() == [sil.EXECUTE, 30, 0, 563, 725, 0, 0, 0], "pump not proven -> remain 0"
    plc.follow_pump_aux()
    plc.set_press_bar(4.2)
    plc.scan(2)
    assert regs() == [sil.EXECUTE, 30, 0, 563, 725, 420, 0, 40]
    plc.run(seconds=10)
    assert 29 <= plc.get("HMI_WASH_REMAIN") <= 31

    plc.set("PUMP_AUX", False)        # contactor drops mid-spray: not proven -> remain reads 0
    plc.scan(2)
    assert plc.get("HMI_WASH_REMAIN") == 0
    plc.set("PUMP_AUX", True)         # proven again: the part gets a full wash time over
    plc.scan(2)
    assert plc.get("HMI_WASH_REMAIN") == 40
    plc.run(seconds=41)
    plc.set_press_bar(0.0)
    plc.follow_pump_aux()
    plc.scan(2)
    assert regs() == [sil.EXECUTE, 40, 0, 563, 725, 0, 1, 0]

    plc.set_temp_c(30.0)              # HMI values follow the process, alarm word too
    plc.scan(2)
    assert plc.get("HMI_TANK_TEMP") == 300
    assert plc.get("HMI_ALARMS") == 1 << sil.ALM["TEMP_LOW"]


def test_fds_7_temp_setpoint_change_at_runtime_moves_heater_band(idle):
    """FDS section 5: 'Setpoints are supervisor-level HMI writes to %MW0..5'; FDS 6.1 heater
    band follows SP_TEMP_X10 / SP_TEMP_HYST_X10 as written, without a restart."""
    plc = idle
    plc.set_temp_c(55.5)
    plc.scan(2)
    assert not plc.get("HEATER_ON")

    plc.set("SP_TEMP_X10", 600)       # tank static at 55.5, SP raised to 60 -> heat
    plc.scan(2)
    assert plc.get("HEATER_ON")
    plc.set_temp_c(59.5)
    plc.scan(2)
    assert plc.get("HEATER_ON"), "58..60 band, stays on"
    plc.set_temp_c(60.1)
    plc.scan(2)
    assert not plc.get("HEATER_ON")

    plc.set("SP_TEMP_HYST_X10", 50)   # 5 degC band: 55..60
    plc.set_temp_c(56.0)
    plc.scan(2)
    assert not plc.get("HEATER_ON"), "inside the wider band, stays off"
    plc.set_temp_c(54.9)
    plc.scan(2)
    assert plc.get("HEATER_ON")

    plc.set("SP_TEMP_X10", 500)       # SP lowered below the tank -> heat off at once
    plc.scan(2)
    assert not plc.get("HEATER_ON")
    assert not plc.alarm(sil.ALM["TEMP_HIGH"]), "54.9 is inside SP + 10"


def test_fds_7_fill_setpoint_change_at_runtime(idle):
    """IO list HR1028 SP_FILL_PCT_X10: 'Make-up water on below % x10 (off at +5 %)' - a
    supervisor write with the level static drives the valve."""
    plc = idle
    plc.set_level_pct(80.0)
    plc.scan(2)
    assert not plc.get("FILL_VALVE")
    plc.set("SP_FILL_PCT_X10", 850)
    plc.scan(2)
    assert plc.get("FILL_VALVE"), "80 % is below the new 85 % setpoint"
    plc.set("SP_FILL_PCT_X10", 700)
    plc.scan(2)
    assert not plc.get("FILL_VALVE"), "80 % is above 70 + 5 %"
    plc.set("SP_FILL_PCT_X10", 780)
    plc.scan(2)
    assert not plc.get("FILL_VALVE"), "inside the 78..83 band, no chatter"


def test_fds_7_timing_setpoints_take_effect_mid_step(in_cycle):
    """IO list HR1026/1027/1029: SP_WASH_TIME_S, SP_JAM_TIME_S and SP_BLOCKED_WARN_S are
    live setpoints - a timer already running follows the new value on the next scan."""
    plc = in_cycle
    plc.set("PE_INFEED", True)
    plc.scan(2)
    assert plc.seq() == 20
    plc.run(seconds=5)
    assert not plc.alarm(sil.ALM["JAM"]), "8 s default"
    plc.set("SP_JAM_TIME_S", 4)
    plc.scan(2)
    assert plc.alarm(sil.ALM["JAM"]) and plc.state() == sil.HELD

    plc.set("PE_INFEED", False)
    plc.set("SP_JAM_TIME_S", 8)
    plc.pulse("PB_RESET")
    plc.pulse("PB_START")
    plc.run(ms=600)
    plc.set("PE_INFEED", True)
    plc.scan(2)
    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    plc.follow_pump_aux()
    plc.scan(2)
    assert plc.seq() == 30 and plc.get("HMI_WASH_REMAIN") == 90
    plc.run(seconds=10)
    assert 79 <= plc.get("HMI_WASH_REMAIN") <= 81
    plc.set("SP_WASH_TIME_S", 12)
    plc.scan(2)
    assert 1 <= plc.get("HMI_WASH_REMAIN") <= 3
    plc.run(seconds=2.5)
    assert plc.seq() == 40 and plc.get("HMI_CYCLE_COUNT") == 1
    plc.follow_pump_aux()

    plc.set("PE_OUTFEED", True)
    plc.run(seconds=3)
    assert not plc.alarm(sil.ALM["BLOCKED"]), "60 s default"
    plc.set("SP_BLOCKED_WARN_S", 2)
    plc.scan(2)
    assert plc.alarm(sil.ALM["BLOCKED"])


def _lights(plc):
    return (plc.get("STACK_RED"), plc.get("STACK_AMBER"), plc.get("STACK_GREEN"), plc.get("HORN"))


def _sample(plc, seconds):
    seen = set()
    for _ in range(int(seconds * 1000 / plc.scan_ms)):
        plc.scan(1)
        seen.add(_lights(plc))
    return seen


def test_fds_7_stack_light_and_horn_per_state(plc):
    """FDS section 7: 'Stack light (CS-0117): red = ABORTED or any critical; amber = HELD or
    any warning; green steady = EXECUTE, green flashing 1 Hz = IDLE ready.' IO list Coil 8:
    horn only on a new critical alarm."""
    assert plc.state() == sil.STOPPED
    assert _sample(plc, 1.2) == {(False, False, False, False)}, "STOPPED: dark, silent"

    plc.pulse("PB_RESET")
    assert plc.state() == sil.IDLE
    seen = _sample(plc, 1.2)
    assert seen == {(False, False, False, False), (False, False, True, False)}, "IDLE: green flashing only"

    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.EXECUTE
    assert _sample(plc, 1.2) == {(False, False, True, False)}, "EXECUTE: steady green"

    plc.set("SEL_AUTO", False)        # HELD with no alarm
    plc.scan(3)
    assert plc.state() == sil.HELD
    assert _sample(plc, 1.2) == {(False, True, False, False)}, "HELD: amber"

    plc.set("ESTOP_OK", False)
    plc.scan(2)
    assert plc.state() == sil.ABORTED
    assert _sample(plc, 1.2) == {(True, False, False, True)}, "ABORTED: red + horn"


def test_fds_7_idle_green_flashes_at_1hz(idle):
    """FDS section 7: 'green flashing 1 Hz = IDLE ready'. IO list Coil 7: 'idle ready (flash 1 Hz)'."""
    plc = idle
    edges, on_scans, prev = 0, [], plc.get("STACK_GREEN")
    run = 0
    for _ in range(int(5000 / plc.scan_ms)):
        plc.scan(1)
        g = plc.get("STACK_GREEN")
        if g and not prev:
            edges += 1
        if g:
            run += 1
        elif prev:
            on_scans.append(run)
            run = 0
        prev = g
    assert 4 <= edges <= 6, f"{edges} rising edges in 5 s is not ~1 Hz"
    for n in on_scans:
        assert 0.4 <= n * plc.scan_ms / 1000 <= 0.65, f"on-phase {n} scans"
