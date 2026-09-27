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


def test_fds_4_1_estop_aborts_from_idle_and_stopped_within_one_scan(idle):
    """FDS 4.1: 'Loss of ESTOP_OK in any state -> ABORTING -> ABORTED within one scan.
    All motion outputs, heater, fill valve off. Red stack light on, horn on.'"""
    plc = idle
    plc.set_temp_c(40.0)
    plc.set_level_pct(50.0)          # heater and make-up water both active in IDLE
    plc.scan(2)
    assert plc.get("HEATER_ON") and plc.get("FILL_VALVE")

    plc.set("ESTOP_OK", False)
    plc.scan(1)
    assert plc.state() == sil.ABORTED
    assert not plc.get("HEATER_ON") and not plc.get("FILL_VALVE")
    assert not plc.get("INFEED_RUN") and not plc.get("PUMP_RUN")
    assert plc.get("STACK_RED") and plc.get("HORN")

    plc.set("ESTOP_OK", True)
    plc.scan(1)
    plc.pulse("PB_RESET")
    assert plc.state() == sil.STOPPED

    plc.set("ESTOP_OK", False)       # and again from STOPPED
    plc.scan(1)
    assert plc.state() == sil.ABORTED
    assert plc.alarm(sil.ALM["ESTOP"])
    assert plc.get("STACK_RED") and plc.get("HORN")


def test_fds_4_2_second_reset_after_abort_reaches_idle(washing):
    """FDS 4.2: 'RESET from ABORTED goes to STOPPED; a second RESET is needed to reach IDLE.'"""
    plc = washing
    plc.set("ESTOP_OK", False)
    plc.scan(2)
    plc.follow_pump_aux()
    plc.set("ESTOP_OK", True)
    plc.scan(2)
    assert plc.state() == sil.ABORTED

    plc.pulse("PB_RESET")
    assert plc.state() == sil.STOPPED
    plc.run(seconds=1)
    assert plc.state() == sil.STOPPED, "one RESET only clears; it must not run on to IDLE"

    plc.pulse("PB_RESET")
    assert plc.state() == sil.IDLE and plc.seq() == 0
    assert plc.get("HMI_ALARMS") == 0
    assert not plc.get("STACK_RED") and not plc.get("HORN")


def test_fds_4_3_stop_from_held_is_controlled_stop_no_red(washing):
    """FDS 4.3: 'STOP pushbutton (NC, 1 = not pressed) from EXECUTE or HELD -> STOPPING ->
    STOPPED. Pump and conveyor commands drop. Not an alarm: no horn, no red light.'"""
    plc = washing
    plc.set("SEL_AUTO", False)        # HELD via MANUAL so no alarm colours the result
    plc.scan(3)
    plc.follow_pump_aux()
    plc.scan(1)
    assert plc.state() == sil.HELD

    plc.set("PB_STOP_NC", False)
    plc.scan(2)
    assert plc.state() == sil.STOPPED and plc.seq() == 0
    assert not plc.get("PUMP_RUN") and not plc.get("INFEED_RUN")
    assert plc.get("HMI_ALARMS") == 0
    assert not plc.get("HORN") and not plc.get("STACK_RED")

    plc.set("PB_STOP_NC", True)
    plc.scan(2)
    assert plc.state() == sil.STOPPED, "releasing STOP does not restart anything"


def test_fds_4_4_new_critical_while_another_active_resounds_horn(washing):
    """FDS 4.4: 'Horn sounds on any new critical alarm for a maximum of 30 s (CS-0117 5.2)
    and is silenced immediately by RESET. A subsequent new critical alarm re-sounds it.'
    The second alarm arrives while the first is still active and already acknowledged."""
    plc = washing
    plc.set("HTR_OK", False)          # first critical alarm: heater high-limit -> HOLD
    plc.scan(2)
    plc.follow_pump_aux()
    plc.scan(1)
    assert plc.state() == sil.HELD and plc.get("HORN")

    plc.pulse("PB_RESET")             # acknowledged; thermostat still open so it stays latched
    assert plc.alarm(sil.ALM["HTR_HILIMIT"])
    assert not plc.get("HORN")
    plc.run(seconds=2)
    assert not plc.get("HORN")

    plc.set("PUMP_OL_OK", False)      # second, unrelated critical alarm
    plc.scan(2)
    assert plc.alarm(sil.ALM["PUMP_OL"])
    assert plc.get("HORN"), "a new critical alarm must re-sound the horn while an acknowledged one is still active"
    plc.run(seconds=29)
    assert plc.get("HORN")
    plc.run(seconds=1.2)
    assert not plc.get("HORN"), "30 s maximum applies to the re-sounded horn too"

    plc.set("INFEED_VFD_RDY", False)  # third critical alarm after the horn timed out
    plc.scan(2)
    assert plc.get("HORN")
    plc.pulse("PB_RESET")
    assert not plc.get("HORN")


def test_fds_4_5_door_lock_held_until_pump_proven_stopped(washing):
    """FDS 4.5: 'Door opened during EXECUTE -> A_GUARD_OPEN (latched) -> HOLD. Door lock
    (SOL-447) is released only after the pump has proven stopped (aux dropped).'"""
    plc = washing
    plc.set("GUARD_CLOSED", False)
    plc.scan(3)
    assert plc.state() == sil.HELD and plc.alarm(sil.ALM["GUARD_OPEN"])
    assert not plc.get("PUMP_RUN")
    assert plc.get("DOOR_LOCK"), "contactor aux still made -> lock stays engaged"
    plc.run(seconds=1)
    assert plc.get("DOOR_LOCK")

    plc.follow_pump_aux()             # contactor drops out
    plc.scan(2)
    assert not plc.get("DOOR_LOCK")

    plc.set("GUARD_CLOSED", True)     # closing the door does not clear the latched alarm
    plc.scan(3)
    assert plc.alarm(sil.ALM["GUARD_OPEN"]) and plc.state() == sil.HELD
    plc.pulse("PB_RESET")
    assert not plc.alarm(sil.ALM["GUARD_OPEN"])
    assert plc.state() == sil.IDLE


def test_fds_4_6_guard_open_in_stopped_is_not_an_alarm(plc):
    """FDS 4.6: 'Door open in IDLE / STOPPED is not an alarm (loading, inspection).'"""
    assert plc.state() == sil.STOPPED
    plc.set("GUARD_CLOSED", False)
    plc.run(seconds=1)
    assert plc.state() == sil.STOPPED
    assert plc.get("HMI_ALARMS") == 0
    assert not plc.get("HORN") and not plc.get("STACK_RED")

    plc.pulse("PB_RESET")             # and it does not block the reset to IDLE
    assert plc.state() == sil.IDLE
    assert not plc.alarm(sil.ALM["GUARD_OPEN"])
