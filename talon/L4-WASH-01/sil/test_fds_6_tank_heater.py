"""FDS-L4-WASH-01 section 6 - tank level, heater control, dry-fire interlock."""
import openplc_sil as sil


def test_6_1_heater_holds_setpoint_with_hysteresis(idle):
    plc = idle
    plc.set("SP_TEMP_X10", 550)
    plc.set("SP_TEMP_HYST_X10", 20)

    plc.set_temp_c(52.0)
    plc.scan(2)
    assert plc.get("HEATER_ON")

    plc.set_temp_c(54.0)     # inside the band, stays on
    plc.scan(2)
    assert plc.get("HEATER_ON")

    plc.set_temp_c(55.5)
    plc.scan(2)
    assert not plc.get("HEATER_ON")

    plc.set_temp_c(53.5)     # inside the band, stays off
    plc.scan(2)
    assert not plc.get("HEATER_ON")

    plc.set_temp_c(52.9)
    plc.scan(2)
    assert plc.get("HEATER_ON")


def test_6_2_heater_never_fires_dry(idle):
    """CS-0088: element burned out in 2019 when the tank drained mid-shift."""
    plc = idle
    plc.set_temp_c(40.0)
    plc.scan(2)
    assert plc.get("HEATER_ON")

    plc.set("LSL_TANK", False)
    plc.scan(2)
    assert not plc.get("HEATER_ON")
    assert plc.alarm(sil.ALM["TANK_LOW"])

    # restoring the switch alone does not clear the latched low alarm
    plc.set("LSL_TANK", True)
    plc.scan(3)
    assert not plc.get("HEATER_ON")
    assert plc.alarm(sil.ALM["TANK_LOW"])

    plc.pulse("PB_RESET")
    assert not plc.alarm(sil.ALM["TANK_LOW"])
    plc.scan(2)
    assert plc.get("HEATER_ON")


def test_6_3_high_limit_trips_heater_and_requires_reset(idle):
    plc = idle
    plc.set_temp_c(40.0)
    plc.scan(2)
    assert plc.get("HEATER_ON")

    plc.set("HTR_OK", False)
    plc.scan(2)
    assert not plc.get("HEATER_ON")
    assert plc.alarm(sil.ALM["HTR_HILIMIT"])

    plc.set("HTR_OK", True)
    plc.scan(3)
    assert not plc.get("HEATER_ON"), "latched until acknowledged"
    plc.pulse("PB_RESET")
    plc.scan(2)
    assert plc.get("HEATER_ON")


def test_6_4_fill_valve_hysteresis(idle):
    plc = idle
    plc.set("SP_FILL_PCT_X10", 700)   # make-up below 70 %, off at 75 %

    plc.set_level_pct(72.0)
    plc.scan(2)
    assert not plc.get("FILL_VALVE")

    plc.set_level_pct(69.0)
    plc.scan(2)
    assert plc.get("FILL_VALVE")

    plc.set_level_pct(73.0)   # inside the 5 % band, keeps filling
    plc.scan(2)
    assert plc.get("FILL_VALVE")

    plc.set_level_pct(75.5)
    plc.scan(2)
    assert not plc.get("FILL_VALVE")


def test_6_5_high_level_switch_closes_fill_valve_regardless_of_transmitter(idle):
    plc = idle
    plc.set_level_pct(60.0)
    plc.scan(2)
    assert plc.get("FILL_VALVE")

    plc.set("LSH_TANK", True)     # transmitter still says 60 %
    plc.scan(2)
    assert not plc.get("FILL_VALVE")
    assert plc.alarm(sil.ALM["TANK_HIGH"])


def test_6_6_low_temperature_is_a_warning_and_only_in_cycle(in_cycle):
    plc = in_cycle
    plc.set_temp_c(30.0)
    plc.run(seconds=1)
    assert plc.alarm(sil.ALM["TEMP_LOW"])
    assert plc.state() == sil.EXECUTE, "cold bath is a quality warning, not a stop"
    assert plc.get("STACK_AMBER")

    plc.set("PB_STOP_NC", False)
    plc.scan(3)
    plc.set("PB_STOP_NC", True)
    plc.scan(2)
    assert plc.state() == sil.STOPPED
    assert not plc.alarm(sil.ALM["TEMP_LOW"]), "not evaluated outside EXECUTE"


def test_6_7_temperature_transmitter_fault_holds_last_good_value(idle):
    plc = idle
    plc.set_temp_c(55.0)
    plc.scan(2)
    assert plc.get("HMI_TANK_TEMP") == 550

    plc.set("TANK_TEMP_RAW", -32768)  # open loop / broken wire
    plc.scan(2)
    assert plc.alarm(sil.ALM["TT_FAIL"])
    assert plc.get("HMI_TANK_TEMP") == 550
    assert not plc.get("HEATER_ON"), "no heating on a failed transmitter"
