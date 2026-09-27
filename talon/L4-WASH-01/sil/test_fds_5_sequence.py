"""FDS-L4-WASH-01 section 5 - wash sequence, conveyor interlocks, jam detection."""
import openplc_sil as sil


def test_5_1_start_is_refused_without_permissives(idle):
    plc = idle
    plc.set("SEL_AUTO", False)   # MANUAL
    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.IDLE

    plc.set("SEL_AUTO", True)
    plc.set("LSL_TANK", False)   # tank below low
    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.IDLE


def test_5_2_full_cycle_indexes_sprays_and_indexes_out(in_cycle):
    plc = in_cycle
    plc.set("SP_WASH_TIME_S", 30)

    plc.set("PE_INFEED", True)
    plc.scan(2)
    assert plc.seq() == 20 and plc.get("INFEED_RUN")
    assert not plc.get("PUMP_RUN")

    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    assert plc.seq() == 30
    assert not plc.get("INFEED_RUN"), "conveyor must stop once the part breaks the chamber beam"
    assert plc.get("PUMP_RUN") and plc.get("DOOR_LOCK")

    plc.follow_pump_aux()
    plc.scan(2)
    assert plc.get("HMI_WASH_REMAIN") == 30
    plc.run(seconds=15)
    assert 14 <= plc.get("HMI_WASH_REMAIN") <= 16

    plc.run(seconds=16)
    assert plc.seq() == 40
    assert plc.get("HMI_CYCLE_COUNT") == 1
    assert not plc.get("PUMP_RUN")
    plc.follow_pump_aux()
    plc.scan(2)
    assert not plc.get("DOOR_LOCK")
    assert plc.get("INFEED_RUN")

    plc.set("PE_CHAMBER", False)
    plc.set("PE_INFEED", False)
    plc.scan(2)
    assert plc.seq() == 10
    assert not plc.get("INFEED_RUN")


def test_5_3_wash_timer_only_counts_while_pump_is_proven(in_cycle):
    plc = in_cycle
    plc.set("SP_WASH_TIME_S", 20)
    plc.set("PE_INFEED", True)
    plc.scan(2)
    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    assert plc.seq() == 30
    # contactor never pulls in -> aux never seen
    plc.run(seconds=2)
    assert plc.get("HMI_WASH_REMAIN") == 0 or plc.get("HMI_WASH_REMAIN") == 20
    plc.run(seconds=2)
    assert plc.alarm(sil.ALM["PUMP_FTS"]), "fail-to-start after 3 s without aux"
    assert plc.state() == sil.HELD
    assert not plc.get("PUMP_RUN")


def test_5_4_downstream_full_blocks_index_out_and_warns(washing):
    plc = washing
    plc.set("SP_WASH_TIME_S", 5)
    plc.set("SP_BLOCKED_WARN_S", 10)
    plc.run(seconds=7)
    assert plc.seq() == 40
    plc.follow_pump_aux()

    plc.set("PE_OUTFEED", True)  # next station still holding its part
    plc.scan(2)
    assert not plc.get("INFEED_RUN")
    assert not plc.alarm(sil.ALM["BLOCKED"])
    plc.run(seconds=11)
    assert plc.alarm(sil.ALM["BLOCKED"])
    assert plc.get("STACK_AMBER")
    assert plc.state() == sil.EXECUTE, "blocked is a warning, machine stays in cycle"

    plc.set("PE_OUTFEED", False)
    plc.set("PE_CHAMBER", False)
    plc.scan(2)
    assert not plc.alarm(sil.ALM["BLOCKED"])
    assert plc.seq() in (10, 20)


def test_5_5_conveyor_jam_after_setpoint_holds_machine(in_cycle):
    plc = in_cycle
    plc.set("SP_JAM_TIME_S", 6)
    plc.set("PE_INFEED", True)
    plc.scan(2)
    assert plc.seq() == 20 and plc.get("INFEED_RUN")

    plc.run(seconds=5.5)
    assert not plc.alarm(sil.ALM["JAM"])
    plc.run(seconds=1)
    assert plc.alarm(sil.ALM["JAM"])
    assert plc.state() == sil.HELD
    assert not plc.get("INFEED_RUN")

    # clear the jam, reset, restart from a clean sequence
    plc.set("PE_INFEED", False)
    plc.pulse("PB_RESET")
    assert not plc.alarm(sil.ALM["JAM"])
    assert plc.state() == sil.IDLE
    assert plc.seq() == 0


def test_5_6_switching_to_manual_in_cycle_holds(washing):
    plc = washing
    plc.set("SEL_AUTO", False)
    plc.scan(3)
    assert plc.state() == sil.HELD
    assert not plc.get("PUMP_RUN") and not plc.get("INFEED_RUN")


def test_5_7_cycle_counter_increments_once_per_part(in_cycle):
    plc = in_cycle
    plc.set("SP_WASH_TIME_S", 2)
    for expected in (1, 2, 3):
        plc.set("PE_INFEED", True)
        plc.scan(2)
        plc.set("PE_CHAMBER", True)
        plc.scan(2)
        plc.follow_pump_aux()
        plc.run(seconds=3)
        assert plc.seq() == 40
        assert plc.get("HMI_CYCLE_COUNT") == expected
        plc.follow_pump_aux()
        plc.set("PE_CHAMBER", False)
        plc.set("PE_INFEED", False)
        plc.scan(2)
        assert plc.seq() == 10


def test_fds_5_1_start_refused_on_door_open_or_critical_and_allowed_cold(idle):
    """FDS 3.1 / 5.1: 'Permissives to start (all required): AUTO selected, door closed,
    LSL_TANK made, no critical alarm active. Temperature is not a start permissive - the
    shift can start on a cold tank and the temp-low warning tells the operator.'"""
    plc = idle
    plc.set("GUARD_CLOSED", False)
    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.IDLE, "door open"
    plc.set("GUARD_CLOSED", True)

    plc.set("INFEED_VFD_RDY", False)  # critical, non-latched alarm
    plc.scan(1)
    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.IDLE, "critical alarm active"
    plc.set("INFEED_VFD_RDY", True)
    plc.scan(1)

    plc.set_temp_c(20.0)              # cold tank is not a permissive
    plc.scan(1)
    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.EXECUTE and plc.seq() == 10


def test_fds_5_3_pump_fail_to_stop_alarms_and_holds(washing):
    """FDS 5.3: 'If aux remains 3 s after the command drops -> same alarm (fail-to-stop).'
    Alarm list bit 7: 'HOLD: pump command removed ... Clears: RESET'."""
    plc = washing
    plc.set("SP_WASH_TIME_S", 5)
    plc.run(seconds=6)
    assert plc.seq() == 40 and not plc.get("PUMP_RUN")

    # welded contactor: aux stays made after the command dropped
    plc.run(seconds=2)
    assert not plc.alarm(sil.ALM["PUMP_FTS"]) and plc.state() == sil.EXECUTE
    assert plc.get("DOOR_LOCK"), "pump still proven running -> door stays locked"
    plc.run(seconds=1.5)
    assert plc.alarm(sil.ALM["PUMP_FTS"]), "fail-to-stop after 3 s with aux still made"
    assert plc.state() == sil.HELD
    assert plc.get("DOOR_LOCK")

    plc.follow_pump_aux()             # contactor finally drops out
    plc.scan(2)
    assert not plc.get("DOOR_LOCK")
    plc.pulse("PB_RESET")
    assert not plc.alarm(sil.ALM["PUMP_FTS"])
    assert plc.state() == sil.IDLE, "one RESET clears the pump fault and releases HELD"


def test_fds_5_5_held_reset_start_restarts_sequence_from_step_10(washing):
    """FDS 5.5: 'RESET -> IDLE, sequence restarts from step 10 on START.' FDS section 3:
    HELD -> 'IDLE on RESET (cause cleared, AUTO, door closed)'. A cycle interrupted by a
    HOLD is not resumed mid-step: the spray timer restarts and the part is not counted."""
    plc = washing
    plc.set("SP_WASH_TIME_S", 30)
    plc.run(seconds=10)
    assert 19 <= plc.get("HMI_WASH_REMAIN") <= 21

    plc.set("SEL_AUTO", False)
    plc.scan(3)
    plc.follow_pump_aux()
    plc.scan(1)
    assert plc.state() == sil.HELD and plc.seq() == 30
    assert plc.get("HMI_WASH_REMAIN") == 0

    plc.set("SEL_AUTO", True)         # cause cleared alone does not un-hold
    plc.run(seconds=1)
    assert plc.state() == sil.HELD

    plc.pulse("PB_RESET")
    assert plc.state() == sil.IDLE and plc.seq() == 0
    assert plc.get("HMI_CYCLE_COUNT") == 0, "interrupted part is not counted"

    plc.set_many(PE_INFEED=False, PE_CHAMBER=False)   # operator pulled the part
    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.EXECUTE and plc.seq() == 10, "restart from step 10, not 30"

    plc.set("PE_INFEED", True)        # part reloaded
    plc.scan(2)
    plc.set("PE_CHAMBER", True)
    plc.scan(2)
    assert plc.seq() == 30
    plc.follow_pump_aux()
    plc.scan(2)
    assert plc.get("HMI_WASH_REMAIN") == 30, "spray timer restarted, not resumed at 20 s"


def test_fds_5_7_cycle_counter_wraps_at_32767_never_negative(in_cycle):
    """FDS 5.7: 'Cycle counter increments exactly once per part at the end of step 30.'
    IO list HR6: 'Parts washed since reset, wraps at 32767' - the MES shift count must
    never read negative."""
    plc = in_cycle
    plc.set("SP_WASH_TIME_S", 1)

    def wash_one():
        plc.set("PE_INFEED", True)
        plc.set("PE_CHAMBER", True)
        plc.scan(2)
        plc.set("PUMP_AUX", True)
        plc.run(seconds=1.1)
        plc.set("PUMP_AUX", False)
        plc.set("PE_CHAMBER", False)
        plc.set("PE_INFEED", False)
        plc.scan(1)

    for _ in range(32767):
        wash_one()
    assert plc.get("HMI_CYCLE_COUNT") == 32767
    assert plc.state() == sil.EXECUTE and plc.seq() == 10

    wash_one()
    assert plc.get("HMI_CYCLE_COUNT") == 0, "wraps to zero, never negative"
    wash_one()
    assert plc.get("HMI_CYCLE_COUNT") == 1
