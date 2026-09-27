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


def test_fds_6_1_heater_permitted_in_idle_held_never_stopped_aborted(plc):
    """FDS 6.1: 'Heaters are permitted in IDLE and HELD (tank pre-heat) but never in
    STOPPED / ABORTING / ABORTED.'"""
    plc.set_temp_c(40.0)
    plc.scan(2)
    assert plc.state() == sil.STOPPED and not plc.get("HEATER_ON")

    plc.pulse("PB_RESET")
    plc.scan(1)
    assert plc.state() == sil.IDLE and plc.get("HEATER_ON")

    plc.pulse("PB_START")
    plc.run(ms=600)
    assert plc.state() == sil.EXECUTE and plc.get("HEATER_ON")

    plc.set("SEL_AUTO", False)
    plc.scan(3)
    assert plc.state() == sil.HELD and plc.get("HEATER_ON")

    plc.set("PB_STOP_NC", False)
    plc.scan(2)
    assert plc.state() == sil.STOPPED and not plc.get("HEATER_ON")
    plc.set("PB_STOP_NC", True)
    plc.set("SEL_AUTO", True)

    plc.set("ESTOP_OK", False)
    plc.scan(2)
    assert plc.state() == sil.ABORTED and not plc.get("HEATER_ON")
    plc.set("ESTOP_OK", True)
    plc.pulse("PB_RESET")
    assert plc.state() == sil.STOPPED and not plc.get("HEATER_ON")
    plc.pulse("PB_RESET")
    plc.scan(1)
    assert plc.state() == sil.IDLE and plc.get("HEATER_ON")


def test_fds_6_1_hysteresis_clamped_to_half_degree(idle):
    """FDS 6.1: 'Hysteresis clamped to >= 0.5 degC.' IO list HR1025: 'clamped >= 5' (x10)."""
    plc = idle
    plc.set("SP_TEMP_X10", 600)
    for bad_hyst in (0, -50):
        plc.set("SP_TEMP_HYST_X10", bad_hyst)
        plc.set_temp_c(59.0)
        plc.scan(2)
        assert plc.get("HEATER_ON")
        plc.set_temp_c(59.8)          # inside the 0.5 degC band, stays on
        plc.scan(2)
        assert plc.get("HEATER_ON"), bad_hyst
        plc.set_temp_c(60.1)
        plc.scan(2)
        assert not plc.get("HEATER_ON"), bad_hyst
        plc.set_temp_c(59.7)          # inside the band, stays off
        plc.scan(2)
        assert not plc.get("HEATER_ON"), bad_hyst
        plc.set_temp_c(59.4)
        plc.scan(2)
        assert plc.get("HEATER_ON"), bad_hyst


def test_fds_6_4_lsl_low_opens_fill_valve_regardless_of_transmitter(idle):
    """FDS 6.4: 'Make-up valve opens below SP_FILL_PCT_X10 (or on LSL_TANK = 0), closes
    at setpoint + 5 %.'"""
    plc = idle
    plc.set_level_pct(80.0)           # LT-444 reads 80 %, SP 65 % -> closed
    plc.scan(2)
    assert not plc.get("FILL_VALVE")

    plc.set("LSL_TANK", False)        # float says LOW while the transmitter still reads 80 %
    plc.scan(2)
    assert plc.get("FILL_VALVE")

    plc.set("LSL_TANK", True)
    plc.scan(2)
    assert not plc.get("FILL_VALVE"), "80 % is above SP + 5 % -> closes again"


def test_fds_6_5_level_transmitter_fault_closes_fill_valve(idle):
    """FDS 6.5: 'Transmitter fault on LT-444 -> valve closed.' Alarm list bit 10:
    'Fill valve closed; level held at last good'."""
    plc = idle
    plc.set_level_pct(50.0)
    plc.scan(2)
    assert plc.get("FILL_VALVE") and plc.get("HMI_TANK_LEVEL") == 500

    plc.set("TANK_LEVEL_RAW", 32767)  # > 20.5 mA, shorted loop
    plc.scan(2)
    assert plc.alarm(sil.ALM["LT_FAIL"])
    assert not plc.get("FILL_VALVE")
    assert plc.get("HMI_TANK_LEVEL") == 500

    plc.set("LSL_TANK", False)        # even a LOW float does not open the valve on a failed LT
    plc.scan(2)
    assert not plc.get("FILL_VALVE")


def test_fds_6_7_level_and_pressure_transmitter_faults_hold_last_good(washing):
    """FDS 6.7: 'Transmitter fault (loop out of range) ... HMI shows last good value.
    Same pattern for LT-444 / PT-445.'"""
    plc = washing
    plc.set_press_bar(4.2)
    plc.scan(2)
    assert plc.get("HMI_PUMP_PRESS") == 420 and plc.get("HMI_TANK_LEVEL") == 800

    plc.set("PUMP_PRESS_RAW", -32768)  # open loop
    plc.set("TANK_LEVEL_RAW", 30000)   # > 20.5 mA
    plc.scan(2)
    assert plc.get("HMI_PUMP_PRESS") == 420
    assert plc.get("HMI_TANK_LEVEL") == 800
    assert plc.alarm(sil.ALM["LT_FAIL"])
    # PT-445 has no row in the alarm list: indication only, nothing else raised
    assert plc.get("HMI_ALARMS") == 1 << sil.ALM["LT_FAIL"]


def test_fds_6_7_transmitter_fault_recovery_clears_alarm_and_resumes(idle):
    """FDS 6.7 with alarm list bits 10/11 'Clears: Loop in range': a transmitter fault is
    not latched; when the loop is back in range the alarm clears without RESET, the HMI
    value follows again and heating / make-up resume."""
    plc = idle
    plc.set_temp_c(45.0)
    plc.scan(2)
    assert plc.get("HEATER_ON") and plc.get("HMI_TANK_TEMP") == 450

    plc.set("TANK_TEMP_RAW", 29500)   # > 20.5 mA
    plc.scan(2)
    assert plc.alarm(sil.ALM["TT_FAIL"]) and plc.get("STACK_RED")
    assert not plc.get("HEATER_ON") and plc.get("HMI_TANK_TEMP") == 450
    plc.run(seconds=5)

    plc.set_temp_c(47.0)              # instrument tech re-terminates the loop
    plc.scan(2)
    assert not plc.alarm(sil.ALM["TT_FAIL"])
    assert plc.get("HMI_TANK_TEMP") == 470
    assert plc.get("HEATER_ON") and not plc.get("STACK_RED")
    assert plc.state() == sil.IDLE

    plc.set_level_pct(50.0)
    plc.scan(2)
    assert plc.get("FILL_VALVE")
    plc.set("TANK_LEVEL_RAW", -32768)
    plc.scan(2)
    assert plc.alarm(sil.ALM["LT_FAIL"]) and not plc.get("FILL_VALVE")
    plc.set_level_pct(52.0)
    plc.scan(2)
    assert not plc.alarm(sil.ALM["LT_FAIL"])
    assert plc.get("FILL_VALVE") and plc.get("HMI_TANK_LEVEL") == 520


def test_fds_6_8_temp_high_is_critical_holds_cycle_and_clears(washing):
    """FDS 6.8: 'TANK_TEMP > SP + 10 degC -> A_TEMP_HIGH (critical).' Alarm list bit 5:
    'Heaters off; cycle HOLD', not latched, 'Clears: Temp < SP + 10'."""
    plc = washing
    plc.set_temp_c(64.5)
    plc.scan(2)
    assert not plc.alarm(sil.ALM["TEMP_HIGH"]) and plc.state() == sil.EXECUTE

    plc.set_temp_c(65.6)
    plc.scan(3)
    plc.follow_pump_aux()
    plc.scan(1)
    assert plc.alarm(sil.ALM["TEMP_HIGH"])
    assert plc.state() == sil.HELD
    assert not plc.get("HEATER_ON") and not plc.get("PUMP_RUN")
    assert plc.get("STACK_RED") and plc.get("HORN")

    plc.set_temp_c(60.0)              # not latched: clears as soon as the temperature drops
    plc.scan(2)
    assert not plc.alarm(sil.ALM["TEMP_HIGH"])
    assert plc.state() == sil.HELD
    plc.pulse("PB_RESET")
    assert plc.state() == sil.IDLE
