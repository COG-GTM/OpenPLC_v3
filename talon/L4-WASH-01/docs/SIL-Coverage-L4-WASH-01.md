# SIL Requirements-Coverage Matrix — L4-WASH-01

**Talon Power Systems — Kingsport Engine Plant — Cell 4-30 PW-430**

| | |
|---|---|
| Document | SIL-Coverage-L4-WASH-01 |
| Against | FDS-L4-WASH-01 Rev F, IO-List-L4-WASH-01.csv, Alarm-List-L4-WASH-01.csv |
| Suite | `talon/L4-WASH-01/sil/` (`make test`) |
| Baseline | 20 tests, 20 passed (`test_fds_4_safety.py` 6, `test_fds_5_sequence.py` 7, `test_fds_6_tank_heater.py` 7) |
| After | 62 tests, 62 passed (+27 named tests, +1 alarm-list bit check, +14 CSV-driven alarm rows); program at Rev G |

Coverage grades: **Full** = every clause of the requirement is asserted by at least one test; **Partial** = the test touches the requirement but leaves a clause unasserted (the gap is stated); **None** = no test exercises it.

Each gap row names the test that closes it. Test naming for new tests: `test_fds_<section>_<short>`, docstring quoting the FDS clause.

## §3 Operating modes and state model

| Req | Requirement (short) | Baseline test(s) | Grade | Gap → new test |
|---|---|---|---|---|
| 3 tbl | PackML state numbers on `HMI_STATE`; entry/exit table | `conftest` fixtures (STOPPED→IDLE→EXECUTE), `test_4_2` (ABORTED→STOPPED), `test_4_3` (→STOPPED), `test_4_5`/`5_6` (→HELD) | Partial | Transient RESETTING(15)/STARTING(3)/STOPPING(7)/CLEARING(1) numbers never observed on HMI_STATE → `test_fds_3_hmi_state_numbers_follow_packml` |
| 3 (power-up) | Power-up state is STOPPED; an unwired controller reports ABORTED, alarm word 0x2305 (README) | none | None | `test_fds_3_power_up_stopped_and_unwired_reports_aborted_0x2305` |
| 3.1 | Start permissives: AUTO, door closed, LSL made, no critical; temperature is *not* a permissive | `test_5_1` (MANUAL, LSL), `conftest.in_cycle` | Partial | Door-open and critical-alarm refusals, cold-tank start allowed → `test_fds_5_1_start_refused_on_door_open_or_critical_and_allowed_cold` |
| 3.2 | MANUAL during a cycle → HOLD | `test_5_6` | Full | — |

## §4 Safety-related behaviour

| Req | Requirement (short) | Baseline test(s) | Grade | Gap → new test |
|---|---|---|---|---|
| 4.1 | Loss of ESTOP_OK *in any state* → ABORTED within one scan; motion, heater, fill off; red + horn | `test_4_1` (from EXECUTE only, 2 scans) | Partial | Abort from IDLE and STOPPED, one-scan latency → `test_fds_4_1_estop_aborts_from_idle_and_stopped_within_one_scan` |
| 4.2 | Leave ABORTED only on ESTOP restored **and** fresh RESET edge; RESET→STOPPED; second RESET→IDLE | `test_4_2` (edge, →STOPPED) | Partial | Second RESET reaching IDLE not asserted → `test_fds_4_2_second_reset_after_abort_reaches_idle` |
| 4.3 | STOP PB from EXECUTE *or HELD* → STOPPING → STOPPED; not an alarm (no horn, no red) | `test_4_3` (from EXECUTE; horn) | Partial | From HELD; red light not asserted → `test_fds_4_3_stop_from_held_is_controlled_stop_no_red` |
| 4.4 | Horn on new critical ≤30 s; RESET silences; subsequent new critical re-sounds | `test_4_4` (30 s timeout; re-sound after the *only* alarm cleared and re-tripped) | Partial | Re-sound when a *second* critical alarm arrives while the first is still active and acknowledged (README lists this as intentionally untested) → `test_fds_4_4_new_critical_while_another_active_resounds_horn` |
| 4.5 | Door open in EXECUTE → A_GUARD_OPEN latched → HOLD; door lock released only after pump aux dropped | `test_4_5` (alarm, HELD, pump off) | Partial | Lock hold-off until aux drops; latch after door re-closed → `test_fds_4_5_door_lock_held_until_pump_proven_stopped` |
| 4.6 | Door open in IDLE / STOPPED is not an alarm | `test_4_6` (IDLE) | Partial | STOPPED → `test_fds_4_6_guard_open_in_stopped_is_not_an_alarm` |

## §5 Wash sequence

| Req | Requirement (short) | Baseline test(s) | Grade | Gap → new test |
|---|---|---|---|---|
| 5 tbl | Steps 10/20/30/40 actions and advance conditions, HMI_STEP | `test_5_2`, `conftest.washing` | Full | — |
| 5.1 | START refused unless 3.1 permissives | `test_5_1` | Partial | see 3.1 |
| 5.2 | Conveyor stops on PE_CHAMBER scan; pump waits for conveyor; door unlocks after pump proven stopped | `test_5_2` | Full | — |
| 5.3 | Spray timer counts only while aux made; fail-to-start 3 s → A_PUMP_FTS + HOLD; **fail-to-stop** 3 s → same alarm | `test_5_3` (timer gating, fail-to-start) | Partial | Fail-to-stop half (README: intentionally untested) → `test_fds_5_3_pump_fail_to_stop_alarms_and_holds` |
| 5.4 | Step 40 blocked: conveyor waits; A_BLOCKED after SP_BLOCKED_WARN_S; stays EXECUTE; clears | `test_5_4` | Full | — |
| 5.5 | Jam after SP_JAM_TIME_S → latched A_JAM, HOLD; RESET → IDLE; restart from step 10 | `test_5_5` (→IDLE, SEQ 0) | Partial | Restart from step 10 on START after a HOLD mid-sequence, interrupted part not counted, wash timer restarted (HOLD → UNHOLD path) → `test_fds_5_5_held_reset_start_restarts_sequence_from_step_10` |
| 5.6 | AUTO→MANUAL in EXECUTE → HOLD | `test_5_6` | Full | — |
| 5.7 | Cycle counter +1 exactly once per part at end of step 30; wraps at 32767 (IO list) | `test_5_7` (1..3) | Partial | Wrap / never-negative on HMI register → `test_fds_5_7_cycle_counter_wraps_at_32767_never_negative` |
| 5 (SP) | Setpoints are HMI writes to `%MW0..5`, defaults per IO list | `test_5_2/5_3/5_4/5_5/6_1/6_4` write SPs *before* the step that uses them | Partial | see §7 setpoints |

## §6 Tank level and temperature

| Req | Requirement (short) | Baseline test(s) | Grade | Gap → new test |
|---|---|---|---|---|
| 6.1 | Heater on ≤ SP−hyst, off ≥ SP; hyst clamp ≥0.5 °C; permitted IDLE/HELD, never STOPPED/ABORTING/ABORTED | `test_6_1` (band, IDLE) | Partial | State permissive and hysteresis clamp → `test_fds_6_1_heater_permitted_in_idle_held_never_stopped_aborted`, `test_fds_6_1_hysteresis_clamped_to_half_degree` |
| 6.2 | Dry-fire: LSL=0 → latched A_TANK_LOW, heaters locked out until RESET with LSL made | `test_6_2` | Full | — |
| 6.3 | HTR_OK=0 → latched A_HTR_HILIMIT, heaters off, RESET clears when restored | `test_6_3` | Full | — |
| 6.4 | Make-up opens below SP_FILL_PCT_X10 **or on LSL=0**, closes at SP+5 % | `test_6_4` (band via transmitter; helper also moves LSL) | Partial | LSL=0 with transmitter above SP → valve opens → `test_fds_6_4_lsl_low_opens_fill_valve_regardless_of_transmitter` |
| 6.5 | LSH=1 → valve closed regardless, A_TANK_HIGH; **LT-444 fault → valve closed** | `test_6_5` (LSH) | Partial | LT fault → `test_fds_6_5_level_transmitter_fault_closes_fill_valve` |
| 6.6 | Temp < SP−2×hyst during EXECUTE → warning; not evaluated outside | `test_6_6` | Full | — |
| 6.7 | Transmitter fault → alarm, heaters off, HMI holds last good; same for LT-444 / PT-445; (recovery when loop back in range) | `test_6_7` (TT-443 only) | Partial | LT/PT last-good, and fault recovery → `test_fds_6_7_level_and_pressure_transmitter_faults_hold_last_good`, `test_fds_6_7_transmitter_fault_recovery_clears_alarm_and_resumes` |
| 6.8 | Temp > SP+10 → A_TEMP_HIGH critical (heaters off, HOLD per alarm list) | none (README: intentionally untested) | None | `test_fds_6_8_temp_high_is_critical_holds_cycle_and_clears` |

## §7 HMI / MES interface

| Req | Requirement (short) | Baseline test(s) | Grade | Gap → new test |
|---|---|---|---|---|
| 7 HR0 `HMI_STATE` | PackML number | all (via `plc.state()`) | Full | — |
| 7 HR1 `HMI_STEP` | 0/10/20/30/40 | `test_5_2` etc. | Full | — |
| 7 HR2 `HMI_ALARMS` | bitmask per alarm list | `plc.alarm()` in many tests (bit *numbers* from `sil.ALM`, never checked against the CSV) | Partial | see Alarm list |
| 7 HR3 `HMI_TANK_TEMP` | °C ×10 | `test_6_7` | Full | — |
| 7 HR4 `HMI_TANK_LEVEL` | % ×10 | none | None | `test_fds_7_status_registers_hr0_to_hr7` |
| 7 HR5 `HMI_PUMP_PRESS` | bar ×100 | none | None | `test_fds_7_status_registers_hr0_to_hr7` |
| 7 HR6 `HMI_CYCLE_COUNT` | parts since reset | `test_5_2`, `test_5_7` | Full | — |
| 7 HR7 `HMI_WASH_REMAIN` | seconds remaining in spray | `test_5_2` | Partial | Zero outside step 30 / while pump not proven → `test_fds_7_status_registers_hr0_to_hr7` |
| 7 HR1024–1029 `%MW0..5` | Setpoint defaults 550/20/90/8/650/60 | none (tests always overwrite) | None | `test_fds_7_setpoint_defaults_match_io_list` |
| 7 `%MW0/1` | Temp SP / hysteresis change **at runtime** moves heater band | none | None | `test_fds_7_temp_setpoint_change_at_runtime_moves_heater_band` |
| 7 `%MW4` | Fill SP change at runtime | `test_6_4` (set before level moves) | Partial | Change while level static → valve reacts → `test_fds_7_fill_setpoint_change_at_runtime` |
| 7 `%MW2/3/5` | Wash / jam / blocked times change while the timer is running | `test_5_2/5_4/5_5` (set before) | Partial | `test_fds_7_timing_setpoints_take_effect_mid_step` |
| 7 Modbus map | Tag ↔ `%IX/%QX/%IW/%QW/%MW` addresses match the IO list | none (harness parses the `.st` only) | None | `test_fds_7_tag_addresses_match_io_list` |
| 7 stack light | red = ABORTED/critical; amber = HELD/warning; green steady = EXECUTE; green flash 1 Hz = IDLE | `test_4_1` (red), `test_4_5`, `test_5_4`/`6_6` (amber) | Partial | Per-state table incl. STOPPED (dark), IDLE flash rate, EXECUTE steady, HELD amber, horn off in non-alarm states → `test_fds_7_stack_light_and_horn_per_state`, `test_fds_7_idle_green_flashes_at_1hz` |

## Alarm list (Alarm-List-L4-WASH-01.csv)

| Bit | Tag | Baseline test(s) | Grade | Gap → new test |
|---|---|---|---|---|
| — | Value column = 2^Bit and matches `sil.ALM` | none | None | `test_fds_alm_bit_values_match_alarm_list` |
| 0 | A_ESTOP | `test_4_1`, `4_2`, `4_4` | Partial | Not latched (follows input) not asserted |
| 1 | A_GUARD_OPEN | `test_4_5`, `4_6` | Partial | Latch + RESET-with-door-closed clear not asserted |
| 2 | A_TANK_LOW | `test_6_2` | Partial | Cycle HOLD + fill valve response not asserted |
| 3 | A_TANK_HIGH | `test_6_5` | Partial | HOLD, non-latched clear on LSH=0 not asserted |
| 4 | A_TEMP_LOW | `test_6_6` | Full | — |
| 5 | A_TEMP_HIGH | none | None | — |
| 6 | A_JAM | `test_5_5` | Full | — |
| 7 | A_PUMP_FTS | `test_5_3` | Partial | Fail-to-stop; RESET clear |
| 8 | A_PUMP_OL | none | None | — |
| 9 | A_VFD_FAULT | none | None | — |
| 10 | A_LT_FAIL | none | None | — |
| 11 | A_TT_FAIL | `test_6_7` | Partial | HOLD, clear on loop-in-range |
| 12 | A_BLOCKED | `test_5_4` | Full | — |
| 13 | A_HTR_HILIMIT | `test_6_3` | Partial | HOLD in cycle |

All 14 rows are closed by one parametrised test driven from the CSV, `test_fds_alm_row[<tag>]`, asserting for each row: bit value, trigger sets exactly that bit, machine response (ABORT / HOLD / none), latched vs. follows-input, and the *Clears* condition.

## Summary

| Section | Requirements | Full | Partial | None |
|---|---|---|---|---|
| §3 | 4 | 1 | 2 | 1 |
| §4 | 6 | 0 | 6 | 0 |
| §5 | 9 | 4 | 5 | 0 |
| §6 | 8 | 3 | 4 | 1 |
| §7 | 14 | 4 | 5 | 5 |
| Alarm list | 15 | 3 | 8 | 4 |
| **Total** | **56** | **15** | **30** | **11** |

Baseline: 20 tests cover 15/56 requirements fully.

## Result

| Section | Requirements | Full (before → after) | Partial | None |
|---|---|---|---|---|
| §3 | 4 | 1 → 4 | 2 → 0 | 1 → 0 |
| §4 | 6 | 0 → 6 | 6 → 0 | 0 |
| §5 | 9 | 4 → 9 | 5 → 0 | 0 |
| §6 | 8 | 3 → 8 | 4 → 0 | 1 → 0 |
| §7 | 14 | 4 → 14 | 5 → 0 | 5 → 0 |
| Alarm list | 15 | 3 → 15 | 8 → 0 | 4 → 0 |
| **Total** | **56** | **15 → 56** | **30 → 0** | **11 → 0** |

Every "Gap → new test" named above exists and passes (`make test`: 62 passed). New files:
`test_fds_3_state_model.py` (2), `test_fds_7_hmi_mes.py` (8), `test_fds_alm_alarm_list.py` (1 + 14 parametrised);
`test_fds_4_safety.py` +6, `test_fds_5_sequence.py` +4, `test_fds_6_tank_heater.py` +7.

### Defects found in the program (fixed in `L4_WASH_01.st` Rev G)

| # | Found by | Requirement | Defect | Fix |
|---|---|---|---|---|
| D1 | `test_fds_4_4_new_critical_while_another_active_resounds_horn` | FDS 4.4 "A subsequent new critical alarm re-sounds it" | `HORN_ACK` was only cleared when *no* critical alarm remained (`IF NOT ANY_CRITICAL THEN HORN_ACK := FALSE`). With one acknowledged alarm still latched (e.g. heater high-limit awaiting the electrician) a second critical alarm (pump overload, VFD fault, …) was silent; if the horn had already timed out (30 s), `T_HORN.Q` stayed true and even a cleared-then-new alarm could not re-sound it. | Critical bits of `HMI_ALARMS` are compared with the previous scan (`CRIT_WORD AND NOT CRIT_WORD_PREV`); a newly set bit clears `HORN_ACK` and restarts `T_HORN` for a fresh 30 s. |
| D2 | `test_fds_5_3_pump_fail_to_stop_alarms_and_holds`, `test_fds_alm_row[A_PUMP_FTS]`, `test_fds_alm_row[A_PUMP_OL]` | FDS §3 HELD → "IDLE on RESET"; FDS 5.5 "RESET → IDLE"; alarm list bits 7/8 "Clears: RESET" | `A_PUMP_FTS` / `A_PUMP_OL` were read from `FB_MOTOR` latches that are cleared by `RT_RESET.Q` in section 5, *after* the HELD state had already evaluated `RT_RESET.Q AND NOT ANY_CRITICAL` in section 4 with the stale alarm. One RESET cleared the alarm but left the machine HELD; a second RESET was needed — contradicting 4.2, which reserves the double RESET for ABORTED. | Section 3 looks through the reset edge: `PUMP_RESET := RT_RESET.Q AND PUMP_OL_OK; A_PUMP_OL := PUMP.FLT_OL AND NOT PUMP_RESET; A_PUMP_FTS := (FLT_FTS OR FLT_FTP) AND NOT PUMP_RESET`, mirroring the FB's own clear condition. |

### Observations not treated as defects

* FDS 6.7 says "same pattern for LT-444 / PT-445" but the alarm list has no PT-445 row and `HMI_ALARMS` has no spare bit assigned; PT-445 is indication only (not used by any interlock). Tests assert last-good hold for PT and no alarm bit; adding a bit is an alarm-list change for the plant to decide.
* Spray timer (`T_WASH`, a TON on `PUMP.RUNNING`) restarts from zero if the contactor aux drops mid-spray rather than pausing. FDS 5.3 "counts only while aux is made" is satisfied conservatively (the part gets a full wash); asserted as-is in `test_fds_7_status_registers_hr0_to_hr7`.
* HOLD → UNHOLD: the program has no PackML UNHOLD path; HELD leaves only via RESET → IDLE → START, and the sequence restarts at step 10 (FDS 5.5, §3 table). Asserted in `test_fds_5_5_held_reset_start_restarts_sequence_from_step_10`.
* Cycle counter reset: HR6 is only cleared by a program download / power cycle; the FDS lists the MES shift-rollover write as out of scope. The wrap at 32767 → 0 is asserted.
