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
