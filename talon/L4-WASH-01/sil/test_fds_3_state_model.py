"""FDS-L4-WASH-01 section 3 - operating modes and PackML state model."""
import openplc_sil as sil


def test_fds_3_hmi_state_numbers_follow_packml(plc):
    """FDS section 3: 'HMI_STATE carries the standard numbers so the Ignition PackML
    faceplate works unmodified' - STOPPED 2, RESETTING 15, IDLE 4, STARTING 3,
    EXECUTE 6, STOPPING 7, ABORTING 8 / ABORTED 9, CLEARING 1, each visible on
    HMI_STATE for the scan the state table says it occupies."""
    assert plc.state() == sil.STOPPED

    plc.set("PB_RESET", True)
    plc.scan(1)
    assert plc.state() == sil.RESETTING, "RESETTING is a one-scan state"
    plc.scan(1)
    assert plc.state() == sil.IDLE
    plc.set("PB_RESET", False)
    plc.scan(1)

    plc.set("PB_START", True)
    plc.scan(1)
    assert plc.state() == sil.STARTING
    plc.set("PB_START", False)
    plc.run(ms=300)
    assert plc.state() == sil.STARTING, "500 ms door settle"
    plc.run(ms=300)
    assert plc.state() == sil.EXECUTE and plc.seq() == 10

    plc.set("PB_STOP_NC", False)
    plc.scan(1)
    assert plc.state() == sil.STOPPING, "STOPPING is a one-scan state"
    plc.scan(1)
    assert plc.state() == sil.STOPPED and plc.seq() == 0
    plc.set("PB_STOP_NC", True)
    plc.scan(1)

    plc.set("ESTOP_OK", False)
    plc.scan(1)
    assert plc.state() == sil.ABORTED, "ABORTING -> ABORTED within one scan (FDS 4.1)"
    plc.set("ESTOP_OK", True)
    plc.scan(1)
    plc.set("PB_RESET", True)
    plc.scan(1)
    assert plc.state() == sil.CLEARING, "CLEARING is a one-scan state"
    plc.scan(1)
    assert plc.state() == sil.STOPPED


def test_fds_3_power_up_stopped_and_unwired_reports_aborted_0x2305():
    """FDS section 3 table: STOPPED is 'Entered from power-up'. talon/README.md: 'With no
    I/O attached the program sits in ABORTED (state 9) with alarm word 0x2305 - E-stop,
    tank low, pump overload, VFD not ready, heater high-limit'."""
    plc = sil.Plc()
    plc.healthy()
    plc.scan(1)
    assert plc.state() == sil.STOPPED and plc.seq() == 0
    assert plc.get("HMI_ALARMS") == 0

    plc.reset()             # power-up again, this time with every input at 0 (unwired)
    plc.scan(2)
    assert plc.state() == sil.ABORTED
    assert plc.get("HMI_ALARMS") == 0x2305
    for bit in ("ESTOP", "TANK_LOW", "PUMP_OL", "VFD_FAULT", "HTR_HILIMIT"):
        assert plc.alarm(sil.ALM[bit]), bit
    assert not plc.get("HEATER_ON") and not plc.get("PUMP_RUN") and not plc.get("INFEED_RUN")
    assert not plc.get("FILL_VALVE"), "not SAFE_OK -> make-up valve closed"
    assert plc.get("STACK_RED") and plc.get("HORN")
