"""FDS-L4-WASH-01 section 4 - safety circuit and abort behaviour."""
import openplc_sil as sil


def test_4_1_estop_from_execute_aborts_and_drops_all_motion(washing):
    plc = washing
    plc.set("ESTOP_OK", False)
    plc.scan(2)

    assert plc.state() == sil.ABORTED
    assert not plc.get("INFEED_RUN")
    assert not plc.get("PUMP_RUN")
    assert not plc.get("HEATER_ON")
    assert not plc.get("FILL_VALVE")
    assert plc.alarm(sil.ALM["ESTOP"])
    assert plc.get("STACK_RED") and plc.get("HORN")


def test_4_2_aborted_requires_safety_restored_and_fresh_reset_edge(washing):
    plc = washing
    plc.set("ESTOP_OK", False)
    plc.scan(2)
    assert plc.state() == sil.ABORTED

    # reset held while E-stop still tripped does nothing
    plc.set("PB_RESET", True)
    plc.scan(3)
    assert plc.state() == sil.ABORTED

    # restoring the safety circuit with reset still held must NOT clear (edge, not level)
    plc.set("ESTOP_OK", True)
    plc.scan(3)
    assert plc.state() == sil.ABORTED

    plc.set("PB_RESET", False)
    plc.scan(1)
    plc.pulse("PB_RESET")
    assert plc.state() == sil.STOPPED
    assert plc.seq() == 0


def test_4_3_stop_pushbutton_is_a_controlled_stop_not_an_abort(washing):
    plc = washing
    plc.set("PB_STOP_NC", False)   # NC contact opens when pressed
    plc.scan(2)
    plc.follow_pump_aux()
    assert not plc.get("PUMP_RUN") and not plc.get("INFEED_RUN")
    assert not plc.get("HORN"), "operator stop is not an alarm"
    plc.set("PB_STOP_NC", True)
    plc.scan(2)
    assert plc.state() == sil.STOPPED
    assert plc.seq() == 0


def test_4_4_horn_self_silences_after_30s_and_reset_acks_it(washing):
    plc = washing
    plc.set("ESTOP_OK", False)
    plc.scan(2)
    plc.follow_pump_aux()   # contactor drops out, otherwise fail-to-stop keeps the horn alive
    assert plc.get("HORN")
    plc.run(seconds=29)
    assert plc.get("HORN")
    plc.run(seconds=1.2)
    assert not plc.get("HORN"), "horn must time out at 30 s per CS-0117"

    # a new critical alarm re-sounds it, reset silences immediately
    plc.set("ESTOP_OK", True)
    plc.scan(2)
    plc.set("ESTOP_OK", False)
    plc.scan(2)
    assert plc.get("HORN")
    plc.pulse("PB_RESET")
    assert not plc.get("HORN")


def test_4_5_guard_open_in_cycle_holds_machine(washing):
    plc = washing
    plc.set("GUARD_CLOSED", False)
    plc.scan(3)
    assert plc.state() == sil.HELD
    assert plc.alarm(sil.ALM["GUARD_OPEN"])
    assert not plc.get("PUMP_RUN")
    assert plc.get("STACK_AMBER") or plc.get("STACK_RED")


def test_4_6_guard_open_while_idle_is_not_an_alarm(idle):
    plc = idle
    plc.set("GUARD_CLOSED", False)
    plc.scan(3)
    assert not plc.alarm(sil.ALM["GUARD_OPEN"])
    assert plc.state() == sil.IDLE
