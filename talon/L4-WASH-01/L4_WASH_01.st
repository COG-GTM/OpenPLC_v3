(*=====================================================================================
  Talon Power Systems - Kingsport Engine Plant
  Line 4 Cylinder Block Machining / Cell 4-30 Aqueous Parts Washer

  Program  : L4_WASH_01
  Asset    : PW-430  (Cinetic / Proceco style single-chamber spray washer, gas-fired
                     tank replaced with 3x 18 kW immersion heaters in 2019 retrofit)
  Target   : OpenPLC Runtime v3, blank_linux hardware layer (I/O via Modbus/TCP)
  Standard : IEC 61131-3 Structured Text, PackML (ISA-TR88.00.02) state model
  Spec     : docs/FDS-L4-WASH-01.md, docs/IO-List-L4-WASH-01.csv,
             docs/Alarm-List-L4-WASH-01.csv

  Rev  Date        By    Description
  ---  ----------  ----  ------------------------------------------------------------
  A    2019-03-12  RJM   Initial release for heater retrofit (ported from SLC 5/04)
  B    2019-06-04  RJM   Added dry-fire interlock on heaters after HTR-2 element failure
  C    2021-11-18  DKP   Jam timer changed from fixed 5 s to HMI setpoint MW3
  D    2023-02-27  DKP   Downstream-blocked warning, stack light per plant std CS-0117
  E    2024-09-09  TLS   Ported to OpenPLC for SIL bench; no functional change intended
  F    2025-01-21  TLS   SIL findings: STOP PB is a controlled stop (was aborting via
                         SAFE_OK), tank-low and high-limit heater lockouts now latch
                         until RESET (CS-0088 review)
  G    2026-09-27  DEV   SIL coverage to FDS Rev F: horn re-sounds on a new critical
                         alarm while an acknowledged one is still active (4.4); pump
                         FTS/FTP/OL faults clear and release HELD on one RESET (5.5,
                         alarm list bits 7/8)
=====================================================================================*)

(*-------------------------------------------------------------------------------------
  FB_SCALE_AI  -  4-20 mA analog input scaling with transmitter health

  RAW is the 0..27648 engineering count convention (Siemens style, kept from the
  S7-1200 remote I/O drop). Values below RAW_LO_LIMIT or above RAW_HI_LIMIT indicate an
  open loop / short and set FAULT. Output is held at the last good value while faulted.
-------------------------------------------------------------------------------------*)
FUNCTION_BLOCK FB_SCALE_AI
  VAR_INPUT
    RAW      : INT;
    EU_MIN   : REAL;
    EU_MAX   : REAL;
  END_VAR
  VAR_OUTPUT
    EU       : REAL;
    FAULT    : BOOL;
  END_VAR
  VAR
    RAW_LO_LIMIT : INT := -1382;   (* ~3.5 mA *)
    RAW_HI_LIMIT : INT := 29030;   (* ~20.5 mA *)
    LAST_GOOD    : REAL;
  END_VAR

  IF RAW < RAW_LO_LIMIT OR RAW > RAW_HI_LIMIT THEN
    FAULT := TRUE;
    EU := LAST_GOOD;
  ELSE
    FAULT := FALSE;
    EU := EU_MIN + (EU_MAX - EU_MIN) * INT_TO_REAL(RAW) / 27648.0;
    LAST_GOOD := EU;
  END_IF;
END_FUNCTION_BLOCK


(*-------------------------------------------------------------------------------------
  FB_MOTOR  -  Contactor-driven motor with run feedback

  Fail-to-start: RUN commanded, AUX not seen within FB_TIME.
  Fail-to-stop : RUN dropped, AUX still made after FB_TIME.
  Either latches FAULT until RESET. The output is forced off while faulted.
-------------------------------------------------------------------------------------*)
FUNCTION_BLOCK FB_MOTOR
  VAR_INPUT
    CMD      : BOOL;
    AUX      : BOOL;
    OL_OK    : BOOL;
    PERMIT   : BOOL;
    RESET    : BOOL;
    FB_TIME  : TIME := T#3s;
  END_VAR
  VAR_OUTPUT
    RUN      : BOOL;
    RUNNING  : BOOL;
    FAULT    : BOOL;
    FLT_FTS  : BOOL;
    FLT_FTP  : BOOL;
    FLT_OL   : BOOL;
  END_VAR
  VAR
    T_FTS    : TON;
    T_FTP    : TON;
  END_VAR

  RUN := CMD AND PERMIT AND OL_OK AND NOT FAULT;
  RUNNING := AUX;

  T_FTS(IN := RUN AND NOT AUX, PT := FB_TIME);
  T_FTP(IN := NOT RUN AND AUX, PT := FB_TIME);

  IF T_FTS.Q THEN FLT_FTS := TRUE; END_IF;
  IF T_FTP.Q THEN FLT_FTP := TRUE; END_IF;
  IF NOT OL_OK THEN FLT_OL := TRUE; END_IF;

  IF RESET AND OL_OK THEN
    FLT_FTS := FALSE;
    FLT_FTP := FALSE;
    FLT_OL  := FALSE;
  END_IF;

  FAULT := FLT_FTS OR FLT_FTP OR FLT_OL;
END_FUNCTION_BLOCK


(*=====================================================================================
  MAIN PROGRAM
=====================================================================================*)
PROGRAM L4_WASH_01
  VAR
    (*---- Discrete inputs -- see IO list, rack 1 slot 2 (16 pt 24 VDC sink) ----*)
    ESTOP_OK        AT %IX0.0 : BOOL;   (* K1 safety relay, ch 1+2 monitored, 1 = healthy *)
    GUARD_CLOSED    AT %IX0.1 : BOOL;   (* ZS-431 chamber door, 1 = closed *)
    PB_RESET        AT %IX0.2 : BOOL;   (* HS-432 blue PB, momentary *)
    PB_START        AT %IX0.3 : BOOL;   (* HS-433 green PB, momentary *)
    PB_STOP_NC      AT %IX0.4 : BOOL;   (* HS-434 red PB, NC contact, 1 = not pressed *)
    SEL_AUTO        AT %IX0.5 : BOOL;   (* HS-435 2-pos selector, 1 = AUTO, 0 = MANUAL *)
    PE_INFEED       AT %IX0.6 : BOOL;   (* ZE-436 retroreflective, 1 = part present *)
    PE_CHAMBER      AT %IX0.7 : BOOL;   (* ZE-437 thru-beam, 1 = part in chamber *)
    PE_OUTFEED      AT %IX1.0 : BOOL;   (* ZE-438, 1 = part at outfeed / downstream full *)
    LSL_TANK        AT %IX1.1 : BOOL;   (* LSL-441 float, 1 = level ABOVE low (fail safe) *)
    LSH_TANK        AT %IX1.2 : BOOL;   (* LSH-442 float, 1 = level above high *)
    PUMP_AUX        AT %IX1.3 : BOOL;   (* M2 contactor aux, 1 = pump running *)
    INFEED_VFD_RDY  AT %IX1.4 : BOOL;   (* VFD-1 ready / no fault *)
    PUMP_OL_OK      AT %IX1.5 : BOOL;   (* OL2 overload, 1 = healthy *)
    HTR_OK          AT %IX1.6 : BOOL;   (* HTR-1..3 high-limit thermostats series, 1 = ok *)

    (*---- Analog inputs -- rack 1 slot 4 (4 ch 4-20 mA), 0..27648 counts ----*)
    TANK_TEMP_RAW   AT %IW0 : INT;      (* TT-443 RTD xmtr, 0..100 degC *)
    TANK_LEVEL_RAW  AT %IW1 : INT;      (* LT-444 hydrostatic, 0..100 % *)
    PUMP_PRESS_RAW  AT %IW2 : INT;      (* PT-445 spray header, 0..10 bar *)

    (*---- Discrete outputs -- rack 1 slot 3 (16 pt 24 VDC source) ----*)
    INFEED_RUN      AT %QX0.0 : BOOL;   (* VFD-1 run fwd *)
    PUMP_RUN        AT %QX0.1 : BOOL;   (* M2 wash pump contactor *)
    HEATER_ON       AT %QX0.2 : BOOL;   (* K3 heater contactor (all 3 elements) *)
    FILL_VALVE      AT %QX0.3 : BOOL;   (* SOV-446 fresh water make-up *)
    DOOR_LOCK       AT %QX0.4 : BOOL;   (* SOL-447 chamber door lock *)
    STACK_RED       AT %QX0.5 : BOOL;
    STACK_AMBER     AT %QX0.6 : BOOL;
    STACK_GREEN     AT %QX0.7 : BOOL;
    HORN            AT %QX1.0 : BOOL;

    (*---- HMI / MES words (Modbus holding regs, see Modbus map) ----*)
    HMI_STATE       AT %QW0 : INT;      (* PackML state number *)
    HMI_STEP        AT %QW1 : INT;      (* wash sequence step *)
    HMI_ALARMS      AT %QW2 : INT;      (* alarm bits, see alarm list *)
    HMI_TANK_TEMP   AT %QW3 : INT;      (* degC x10 *)
    HMI_TANK_LEVEL  AT %QW4 : INT;      (* % x10 *)
    HMI_PUMP_PRESS  AT %QW5 : INT;      (* bar x100 *)
    HMI_CYCLE_COUNT AT %QW6 : INT;      (* parts washed since reset, wraps at 32767 *)
    HMI_WASH_REMAIN AT %QW7 : INT;      (* seconds remaining in wash step *)

    SP_TEMP_X10     AT %MW0 : INT := 550;   (* wash temp setpoint degC x10 *)
    SP_TEMP_HYST_X10 AT %MW1 : INT := 20;   (* heater hysteresis degC x10 *)
    SP_WASH_TIME_S  AT %MW2 : INT := 90;    (* spray time per part, s *)
    SP_JAM_TIME_S   AT %MW3 : INT := 8;     (* conveyor index without PE_CHAMBER, s *)
    SP_FILL_PCT_X10 AT %MW4 : INT := 650;   (* start make-up below this level, % x10 *)
    SP_BLOCKED_WARN_S AT %MW5 : INT := 60;  (* downstream blocked warning delay, s *)
  END_VAR

  VAR CONSTANT
    (*---- PackML state numbers (ISA-TR88.00.02) ----*)
    ST_CLEARING  : INT := 1;
    ST_STOPPED   : INT := 2;
    ST_STARTING  : INT := 3;
    ST_IDLE      : INT := 4;
    ST_EXECUTE   : INT := 6;
    ST_STOPPING  : INT := 7;
    ST_ABORTING  : INT := 8;
    ST_ABORTED   : INT := 9;
    ST_HOLDING   : INT := 10;
    ST_HELD      : INT := 11;
    ST_RESETTING : INT := 15;
  END_VAR

  VAR
    STATE        : INT := 2;
    SEQ         : INT := 0;

    (*---- Internals ----*)
    SAFE_OK      : BOOL;
    RUN_PERMIT   : BOOL;
    FIRST_SCAN   : BOOL := TRUE;

    TANK_TEMP    : REAL;
    TANK_LEVEL   : REAL;
    PUMP_PRESS   : REAL;
    SP_TEMP      : REAL;
    SP_HYST      : REAL;
    TEMP_AT_SP   : BOOL;

    AI_TEMP      : FB_SCALE_AI;
    AI_LEVEL     : FB_SCALE_AI;
    AI_PRESS     : FB_SCALE_AI;
    PUMP         : FB_MOTOR;

    RT_START     : R_TRIG;
    RT_RESET     : R_TRIG;
    FT_ESTOP     : F_TRIG;

    T_JAM        : TON;
    T_WASH       : TON;
    T_BLOCKED    : TON;
    T_DOOR_SETTLE : TON;
    T_HORN       : TON;
    T_FLASH      : TON;
    FLASH        : BOOL;

    CYCLE_COUNT  : INT;

    (*---- Alarm bits (bit index = alarm list "Bit" column) ----*)
    A_ESTOP        : BOOL;   (* 0  *)
    A_GUARD_OPEN   : BOOL;   (* 1  *)
    A_TANK_LOW     : BOOL;   (* 2  *)
    A_TANK_HIGH    : BOOL;   (* 3  *)
    A_TEMP_LOW     : BOOL;   (* 4  *)
    A_TEMP_HIGH    : BOOL;   (* 5  *)
    A_JAM          : BOOL;   (* 6  *)
    A_PUMP_FTS     : BOOL;   (* 7  *)
    A_PUMP_OL      : BOOL;   (* 8  *)
    A_VFD_FAULT    : BOOL;   (* 9  *)
    A_LT_FAIL      : BOOL;   (* 10 *)
    A_TT_FAIL      : BOOL;   (* 11 *)
    A_BLOCKED      : BOOL;   (* 12 *)
    A_HTR_HILIMIT  : BOOL;   (* 13 *)
    ANY_CRITICAL   : BOOL;
    ANY_WARNING    : BOOL;
    HORN_ACK       : BOOL;
    PUMP_RESET     : BOOL;
    CRIT_WORD      : WORD;
    CRIT_WORD_PREV : WORD;
    NEW_CRITICAL   : BOOL;
  END_VAR

  (*---------------------------------------------------------------------------------
    1. Analog scaling and setpoints
  ---------------------------------------------------------------------------------*)
  AI_TEMP(RAW := TANK_TEMP_RAW, EU_MIN := 0.0, EU_MAX := 100.0);
  AI_LEVEL(RAW := TANK_LEVEL_RAW, EU_MIN := 0.0, EU_MAX := 100.0);
  AI_PRESS(RAW := PUMP_PRESS_RAW, EU_MIN := 0.0, EU_MAX := 10.0);
  TANK_TEMP := AI_TEMP.EU;
  TANK_LEVEL := AI_LEVEL.EU;
  PUMP_PRESS := AI_PRESS.EU;

  SP_TEMP := INT_TO_REAL(SP_TEMP_X10) / 10.0;
  SP_HYST := INT_TO_REAL(SP_TEMP_HYST_X10) / 10.0;
  IF SP_HYST < 0.5 THEN SP_HYST := 0.5; END_IF;

  (* temp is "at setpoint" for wash permissive once within one hysteresis band below SP *)
  TEMP_AT_SP := TANK_TEMP >= (SP_TEMP - SP_HYST);

  (*---------------------------------------------------------------------------------
    2. Safety and permissives
       ESTOP_OK is the monitored output of the K1 safety relay; the hard-wired circuit
       drops VFD-1 / M2 / K3 independently of this program. What follows is the
       software mirror so the sequence aborts cleanly and the HMI tells the truth.
  ---------------------------------------------------------------------------------*)
  SAFE_OK := ESTOP_OK;
  RT_RESET(CLK := PB_RESET);
  RT_START(CLK := PB_START);
  FT_ESTOP(CLK := ESTOP_OK);

  (*---------------------------------------------------------------------------------
    3. Alarms (evaluated every scan, latched ones cleared by RESET)
  ---------------------------------------------------------------------------------*)
  A_ESTOP      := NOT ESTOP_OK;
  A_TANK_HIGH  := LSH_TANK;
  A_LT_FAIL    := AI_LEVEL.FAULT;
  A_TT_FAIL    := AI_TEMP.FAULT;
  A_TEMP_LOW   := (STATE = ST_EXECUTE) AND (TANK_TEMP < (SP_TEMP - 2.0 * SP_HYST)) AND NOT A_TT_FAIL;
  A_TEMP_HIGH  := (TANK_TEMP > (SP_TEMP + 10.0)) AND NOT A_TT_FAIL;
  A_VFD_FAULT  := NOT INFEED_VFD_RDY;
  (* pump faults latch inside FB_MOTOR and clear on the same RESET edge (section 5);
     look through the edge here so the state machine sees them cleared this scan *)
  PUMP_RESET   := RT_RESET.Q AND PUMP_OL_OK;
  A_PUMP_OL    := PUMP.FLT_OL AND NOT PUMP_RESET;
  A_PUMP_FTS   := (PUMP.FLT_FTS OR PUMP.FLT_FTP) AND NOT PUMP_RESET;

  (* heater lockouts latch: a dry tank or a tripped high-limit needs an operator
     to look at the tank before the elements are re-enabled (CS-0088) *)
  IF NOT LSL_TANK THEN A_TANK_LOW := TRUE; END_IF;
  IF NOT HTR_OK THEN A_HTR_HILIMIT := TRUE; END_IF;

  (* guard open is only an alarm while the machine is in cycle *)
  IF (STATE = ST_EXECUTE) AND NOT GUARD_CLOSED THEN
    A_GUARD_OPEN := TRUE;
  END_IF;

  (* conveyor jam: indexing and no part reached the chamber within SP_JAM_TIME_S *)
  T_JAM(IN := INFEED_RUN AND (SEQ = 20) AND NOT PE_CHAMBER, PT := INT_TO_TIME(SP_JAM_TIME_S));
  IF T_JAM.Q THEN A_JAM := TRUE; END_IF;

  (* downstream blocked: finished part cannot leave, warning only *)
  T_BLOCKED(IN := (SEQ = 40) AND PE_OUTFEED, PT := INT_TO_TIME(SP_BLOCKED_WARN_S));
  A_BLOCKED := T_BLOCKED.Q;

  IF RT_RESET.Q THEN
    A_GUARD_OPEN := FALSE;
    A_JAM := FALSE;
    IF LSL_TANK THEN A_TANK_LOW := FALSE; END_IF;
    IF HTR_OK THEN A_HTR_HILIMIT := FALSE; END_IF;
    HORN_ACK := TRUE;
  END_IF;

  ANY_CRITICAL := A_ESTOP OR A_GUARD_OPEN OR A_TANK_LOW OR A_TANK_HIGH OR A_JAM
                  OR A_PUMP_FTS OR A_PUMP_OL OR A_VFD_FAULT OR A_LT_FAIL OR A_TT_FAIL
                  OR A_HTR_HILIMIT OR A_TEMP_HIGH;
  ANY_WARNING  := A_TEMP_LOW OR A_BLOCKED;

  HMI_ALARMS := BOOL_TO_INT(A_ESTOP)
              + BOOL_TO_INT(A_GUARD_OPEN)  * 2
              + BOOL_TO_INT(A_TANK_LOW)    * 4
              + BOOL_TO_INT(A_TANK_HIGH)   * 8
              + BOOL_TO_INT(A_TEMP_LOW)    * 16
              + BOOL_TO_INT(A_TEMP_HIGH)   * 32
              + BOOL_TO_INT(A_JAM)         * 64
              + BOOL_TO_INT(A_PUMP_FTS)    * 128
              + BOOL_TO_INT(A_PUMP_OL)     * 256
              + BOOL_TO_INT(A_VFD_FAULT)   * 512
              + BOOL_TO_INT(A_LT_FAIL)     * 1024
              + BOOL_TO_INT(A_TT_FAIL)     * 2048
              + BOOL_TO_INT(A_BLOCKED)     * 4096
              + BOOL_TO_INT(A_HTR_HILIMIT) * 8192;

  (* a critical bit that was clear last scan is a new alarm: it un-silences the horn
     even while an acknowledged critical alarm is still active (CS-0117 5.2) *)
  CRIT_WORD      := INT_TO_WORD(HMI_ALARMS) AND WORD#16#2FEF;
  NEW_CRITICAL   := (CRIT_WORD AND NOT CRIT_WORD_PREV) <> WORD#16#0;
  CRIT_WORD_PREV := CRIT_WORD;
  IF NEW_CRITICAL THEN HORN_ACK := FALSE; END_IF;

  (*---------------------------------------------------------------------------------
    4. PackML state machine
  ---------------------------------------------------------------------------------*)
  IF FIRST_SCAN THEN
    STATE := ST_STOPPED;
    SEQ := 0;
    FIRST_SCAN := FALSE;
  END_IF;

  (* abort from any state on loss of safety *)
  IF NOT SAFE_OK AND (STATE <> ST_ABORTED) AND (STATE <> ST_ABORTING) THEN
    STATE := ST_ABORTING;
  END_IF;

  CASE STATE OF
    1: (* CLEARING *)
      SEQ := 0;
      STATE := ST_STOPPED;

    2: (* STOPPED *)
      SEQ := 0;
      IF RT_RESET.Q AND SAFE_OK THEN
        STATE := ST_RESETTING;
      END_IF;

    15: (* RESETTING *)
      PUMP(CMD := FALSE, AUX := PUMP_AUX, OL_OK := PUMP_OL_OK, PERMIT := FALSE, RESET := TRUE);
      STATE := ST_IDLE;

    4: (* IDLE *)
      SEQ := 0;
      IF RT_START.Q AND SEL_AUTO AND GUARD_CLOSED AND LSL_TANK AND NOT ANY_CRITICAL THEN
        STATE := ST_STARTING;
      END_IF;

    3: (* STARTING *)
      T_DOOR_SETTLE(IN := TRUE, PT := T#500ms);
      IF T_DOOR_SETTLE.Q THEN
        T_DOOR_SETTLE(IN := FALSE);
        SEQ := 10;
        STATE := ST_EXECUTE;
      END_IF;

    6: (* EXECUTE - see section 5 for the wash sequence *)
      IF NOT PB_STOP_NC THEN
        STATE := ST_STOPPING;
      ELSIF ANY_CRITICAL OR NOT SEL_AUTO THEN
        STATE := ST_HOLDING;
      END_IF;

    10: (* HOLDING *)
      STATE := ST_HELD;

    11: (* HELD - operator clears the cause, presses RESET then START *)
      IF NOT PB_STOP_NC THEN
        STATE := ST_STOPPING;
      ELSIF RT_RESET.Q AND NOT ANY_CRITICAL AND SEL_AUTO AND GUARD_CLOSED THEN
        STATE := ST_IDLE;
        SEQ := 0;
      END_IF;

    7: (* STOPPING *)
      SEQ := 0;
      STATE := ST_STOPPED;

    8: (* ABORTING *)
      SEQ := 0;
      HORN_ACK := FALSE;
      STATE := ST_ABORTED;

    9: (* ABORTED - requires safety restored AND a fresh RESET edge *)
      IF SAFE_OK AND RT_RESET.Q THEN
        STATE := ST_CLEARING;
      END_IF;

    ELSE
      STATE := ST_ABORTING;
  END_CASE;

  (*---------------------------------------------------------------------------------
    5. Wash sequence (only advances in EXECUTE)
       10  wait for part at infeed
       20  index conveyor until part breaks chamber beam
       30  lock door, spray for SP_WASH_TIME_S (pump must be proven running)
       40  unlock, index out; wait if downstream is full
  ---------------------------------------------------------------------------------*)
  IF STATE = ST_EXECUTE THEN
    CASE SEQ OF
      10:
        IF PE_INFEED THEN SEQ := 20; END_IF;

      20:
        IF PE_CHAMBER THEN SEQ := 30; END_IF;

      30:
        IF NOT TEMP_AT_SP THEN
          (* wait at temperature; A_TEMP_LOW warns after 2x hysteresis *)
          T_WASH(IN := FALSE);
        ELSE
          T_WASH(IN := PUMP.RUNNING, PT := INT_TO_TIME(SP_WASH_TIME_S));
          IF T_WASH.Q THEN
            T_WASH(IN := FALSE);
            CYCLE_COUNT := CYCLE_COUNT + 1;
            IF CYCLE_COUNT < 0 THEN CYCLE_COUNT := 0; END_IF;
            SEQ := 40;
          END_IF;
        END_IF;

      40:
        IF NOT PE_CHAMBER AND NOT PE_OUTFEED THEN
          SEQ := 10;
        END_IF;

      ELSE
        SEQ := 10;
    END_CASE;
  ELSE
    T_WASH(IN := FALSE);
  END_IF;

  (*---------------------------------------------------------------------------------
    6. Outputs
  ---------------------------------------------------------------------------------*)
  RUN_PERMIT := SAFE_OK AND (STATE = ST_EXECUTE);

  (* infeed conveyor indexes on step 20 (part in) and step 40 (part out, downstream clear) *)
  INFEED_RUN := RUN_PERMIT AND INFEED_VFD_RDY AND
                ( (SEQ = 20) OR ((SEQ = 40) AND NOT PE_OUTFEED) );

  (* wash pump: only in step 30, chamber door must be closed, tank must have suction *)
  PUMP(CMD := RUN_PERMIT AND (SEQ = 30) AND TEMP_AT_SP,
       AUX := PUMP_AUX,
       OL_OK := PUMP_OL_OK,
       PERMIT := GUARD_CLOSED AND LSL_TANK,
       RESET := RT_RESET.Q);
  PUMP_RUN := PUMP.RUN;

  (* door lock while spraying, released when pump has proven stopped *)
  DOOR_LOCK := (STATE = ST_EXECUTE) AND (SEQ = 30) OR PUMP.RUNNING;

  (* heaters: dry-fire interlock on LSL, high-limit series, hysteresis on/off around SP.
     Heaters are allowed in IDLE/HELD so the tank is hot when the shift starts, but
     never in ABORTED/STOPPED (plant std CS-0117 sec 4.3). *)
  IF (STATE = ST_ABORTED) OR (STATE = ST_ABORTING) OR (STATE = ST_STOPPED)
     OR A_TANK_LOW OR A_HTR_HILIMIT OR A_TT_FAIL THEN
    HEATER_ON := FALSE;
  ELSIF TANK_TEMP <= (SP_TEMP - SP_HYST) THEN
    HEATER_ON := TRUE;
  ELSIF TANK_TEMP >= SP_TEMP THEN
    HEATER_ON := FALSE;
  END_IF;

  (* make-up water: open below fill SP or on LSL, close on LSH, never on LT fault *)
  IF LSH_TANK OR A_LT_FAIL OR NOT SAFE_OK THEN
    FILL_VALVE := FALSE;
  ELSIF NOT LSL_TANK OR (TANK_LEVEL * 10.0 < INT_TO_REAL(SP_FILL_PCT_X10)) THEN
    FILL_VALVE := TRUE;
  ELSIF TANK_LEVEL * 10.0 >= INT_TO_REAL(SP_FILL_PCT_X10) + 50.0 THEN
    FILL_VALVE := FALSE;
  END_IF;

  (* stack light per CS-0117: red = aborted/critical, amber = held/warning, green = in cycle,
     flashing green = idle & ready *)
  T_FLASH(IN := NOT T_FLASH.Q, PT := T#500ms);
  IF T_FLASH.Q THEN FLASH := NOT FLASH; END_IF;

  STACK_RED   := (STATE = ST_ABORTED) OR ANY_CRITICAL;
  STACK_AMBER := (STATE = ST_HELD) OR ANY_WARNING;
  STACK_GREEN := (STATE = ST_EXECUTE) OR ((STATE = ST_IDLE) AND FLASH);

  (* horn on abort / new critical alarm for max 30 s, silenced by RESET *)
  T_HORN(IN := ANY_CRITICAL AND NOT HORN_ACK AND NOT NEW_CRITICAL, PT := T#30s);
  HORN := ANY_CRITICAL AND NOT HORN_ACK AND NOT T_HORN.Q;
  IF NOT ANY_CRITICAL THEN HORN_ACK := FALSE; END_IF;

  (*---------------------------------------------------------------------------------
    7. HMI / MES words
  ---------------------------------------------------------------------------------*)
  HMI_STATE := STATE;
  HMI_STEP := SEQ;
  HMI_TANK_TEMP := REAL_TO_INT(TANK_TEMP * 10.0);
  HMI_TANK_LEVEL := REAL_TO_INT(TANK_LEVEL * 10.0);
  HMI_PUMP_PRESS := REAL_TO_INT(PUMP_PRESS * 100.0);
  HMI_CYCLE_COUNT := CYCLE_COUNT;
  IF (SEQ = 30) AND T_WASH.IN THEN
    HMI_WASH_REMAIN := SP_WASH_TIME_S - TIME_TO_INT(T_WASH.ET);
  ELSE
    HMI_WASH_REMAIN := 0;
  END_IF;
END_PROGRAM


CONFIGURATION Config0
  RESOURCE Res0 ON PLC
    TASK Main(INTERVAL := T#50ms, PRIORITY := 0);
    PROGRAM Inst0 WITH Main : L4_WASH_01;
  END_RESOURCE
END_CONFIGURATION
