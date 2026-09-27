# Functional Design Specification

**Talon Power Systems — Kingsport Engine Plant**
**Line 4 Cylinder Block Machining — Cell 4-30 Aqueous Parts Washer (PW-430)**

| | |
|---|---|
| Document | FDS-L4-WASH-01 |
| Revision | F (2025-01-21) |
| Program | `L4_WASH_01.st` — IEC 61131-3 ST, OpenPLC Runtime v3 |
| Supersedes | FDS-L4-WASH-01 Rev E (SLC 5/04 ladder references removed) |
| Related | IO-List-L4-WASH-01.csv, Alarm-List-L4-WASH-01.csv, plant std CS-0117 (stack lights / horns), CS-0088 (immersion heater dry-fire protection), electrical dwg E-4-430 sh 1–6 |
| Owner | Controls Engineering, Kingsport |

Revision F incorporates the two findings from the SIL bench regression (`sil/`): the STOP pushbutton was reaching the machine through the safety word and producing an ABORT instead of a controlled stop, and the tank-low / heater high-limit lockouts were following the input instead of latching as CS-0088 requires.

---

## 1. Scope

PW-430 is a single-chamber, pass-through aqueous spray washer between the finish-bore station (Cell 4-20) and deburr (Cell 4-40). Cylinder blocks arrive on a chain conveyor, index into the chamber, are sprayed with heated alkaline solution for a timed period, and index out. The original gas-fired tank heater was replaced in 2019 with three 18 kW immersion elements, which is when the controls moved from the OEM's SLC 5/04 to the current program.

This document describes what the control program does. It does not describe the hard-wired safety circuit (E-4-430 sh 3), which functions independently of the PLC.

## 2. Equipment and I/O summary

| Group | Devices |
|---|---|
| Motion | VFD-1 infeed chain conveyor (PowerFlex 525, run/ready only), M2 wash pump 7.5 kW (contactor + aux + overload) |
| Process | K3 heater contactor (3 elements, series high-limit thermostats), SOV-446 make-up water, SOL-447 chamber door lock |
| Sensing | ZE-436/437/438 part photoeyes (infeed, chamber, outfeed), ZS-431 door switch, LSL-441 / LSH-442 tank floats, TT-443 tank RTD, LT-444 hydrostatic level, PT-445 spray header pressure |
| Operator | HS-432 RESET, HS-433 START, HS-434 STOP (NC), HS-435 AUTO/MANUAL, Werma 640 stack light R/A/G + horn, Ignition Perspective HMI view `PW430` |
| Safety | K1 Pilz PNOZ s3 (E-stop ×2, door switch on the pump/heater channel), monitored output to `ESTOP_OK` |

Full tag/terminal list: `IO-List-L4-WASH-01.csv`. All analogs are 4–20 mA scaled 0..27648 (retained from the S7-1200 remote I/O drop); loop current outside 3.5–20.5 mA is treated as a transmitter fault (section 6.5).

## 3. Operating modes and state model

The machine follows the PackML / ISA-TR88.00.02 state model. Only the states below are used; `HMI_STATE` carries the standard numbers so the Ignition PackML faceplate works unmodified.

| # | State | Entered from | Exits to |
|---|---|---|---|
| 2 | STOPPED | power-up, CLEARING, STOPPING | RESETTING on RESET (safety healthy) |
| 15 | RESETTING | STOPPED | IDLE (one scan; resets FB_MOTOR faults) |
| 4 | IDLE | RESETTING, HELD+RESET | STARTING on START with permissives |
| 3 | STARTING | IDLE | EXECUTE after 500 ms settle |
| 6 | EXECUTE | STARTING | STOPPING (STOP PB), HOLDING (critical alarm or MANUAL) |
| 10/11 | HOLDING / HELD | EXECUTE | IDLE on RESET (cause cleared, AUTO, door closed); STOPPING on STOP PB |
| 7 | STOPPING | EXECUTE, HELD | STOPPED (one scan) |
| 8/9 | ABORTING / ABORTED | any state on `SAFE_OK` = 0 | CLEARING on RESET with safety restored |
| 1 | CLEARING | ABORTED | STOPPED (one scan) |

**3.1 Permissives to start** (all required): AUTO selected, door closed, `LSL_TANK` made, no critical alarm active. Temperature is *not* a start permissive — the shift can start on a cold tank and the temp-low warning tells the operator.

**3.2 MANUAL mode** exists for maintenance jogging from the VFD keypad and is not implemented in this program; selecting MANUAL during a cycle produces a HOLD.

## 4. Safety-related behaviour (software mirror)

`SAFE_OK` is the K1 monitored output only. The STOP pushbutton is an operating control, not a safety function.

| Req | Behaviour |
|---|---|
| 4.1 | Loss of `ESTOP_OK` in any state → ABORTING → ABORTED within one scan. All motion outputs, heater, fill valve off. Red stack light on, horn on. |
| 4.2 | Leaving ABORTED requires `ESTOP_OK` restored **and** a fresh rising edge of RESET (holding RESET through the reset of the safety relay does not clear). RESET from ABORTED goes to STOPPED; a second RESET is needed to reach IDLE. |
| 4.3 | STOP pushbutton (NC, 1 = not pressed) from EXECUTE or HELD → STOPPING → STOPPED. Pump and conveyor commands drop. Not an alarm: no horn, no red light. |
| 4.4 | Horn sounds on any new critical alarm for a maximum of 30 s (CS-0117 §5.2) and is silenced immediately by RESET. A subsequent new critical alarm re-sounds it. |
| 4.5 | Door opened during EXECUTE → `A_GUARD_OPEN` (latched) → HOLD. Door lock (SOL-447) is released only after the pump has proven stopped (aux dropped). |
| 4.6 | Door open in IDLE / STOPPED is not an alarm (loading, inspection). |

## 5. Wash sequence (EXECUTE)

`HMI_STEP` reports the step number.

| Step | Name | Actions | Advance when |
|---|---|---|---|
| 10 | Wait for part | conveyor off | `PE_INFEED` made |
| 20 | Index in | conveyor run; jam timer running | `PE_CHAMBER` made → conveyor off |
| 30 | Spray | door lock; pump run; spray timer counts **only while pump proven running** (aux) | timer = `SP_WASH_TIME_S` → pump off, `HMI_CYCLE_COUNT` += 1 |
| 40 | Index out | conveyor run unless `PE_OUTFEED` made (downstream full) | `PE_CHAMBER` cleared → step 10 |

| Req | Behaviour |
|---|---|
| 5.1 | START is refused unless section 3.1 permissives are all true. |
| 5.2 | Conveyor stops on the scan `PE_CHAMBER` is made; pump does not start until the conveyor has stopped. Door unlocks after the pump has proven stopped. |
| 5.3 | The spray timer counts only while M2 aux is made (a pump that is not proven running is not washing). If aux is not seen within 3 s of the pump command → `A_PUMP_FTS`, HOLD. If aux remains 3 s after the command drops → same alarm (fail-to-stop). |
| 5.4 | Step 40 with `PE_OUTFEED` made: conveyor waits. After `SP_BLOCKED_WARN_S` → `A_BLOCKED` warning (amber), machine stays in EXECUTE. Clears when outfeed clears. |
| 5.5 | Step 20 running for `SP_JAM_TIME_S` without `PE_CHAMBER` → `A_JAM` (latched), HOLD. Operator clears the part, RESET → IDLE, sequence restarts from step 10 on START. |
| 5.6 | AUTO→MANUAL during EXECUTE → HOLD. |
| 5.7 | Cycle counter increments exactly once per part at the end of step 30. Reset to zero by the MES shift rollover write (out of scope here). |

Setpoints are supervisor-level HMI writes to `%MW0..5`; defaults are in the IO list.

## 6. Tank level and temperature

| Req | Behaviour |
|---|---|
| 6.1 | Heater on when `TANK_TEMP` ≤ SP − hyst, off when ≥ SP. Hysteresis clamped to ≥ 0.5 °C. Heaters are permitted in IDLE and HELD (tank pre-heat) but never in STOPPED / ABORTING / ABORTED. |
| 6.2 | **Dry-fire protection (CS-0088).** `LSL_TANK` = 0 sets `A_TANK_LOW` (latched). Heaters are locked out while the alarm is latched, not merely while the float is low. Cleared by RESET only when `LSL_TANK` is made. |
| 6.3 | `HTR_OK` = 0 (any element thermostat tripped) sets `A_HTR_HILIMIT` (latched), heaters off. Cleared by RESET when `HTR_OK` restored. |
| 6.4 | Make-up valve opens below `SP_FILL_PCT_X10` (or on `LSL_TANK` = 0), closes at setpoint + 5 %. |
| 6.5 | `LSH_TANK` = 1 → valve closed regardless of transmitter, `A_TANK_HIGH`. Transmitter fault on LT-444 → valve closed. |
| 6.6 | `TANK_TEMP` < SP − 2×hyst **during EXECUTE** → `A_TEMP_LOW` warning; not evaluated outside EXECUTE. |
| 6.7 | Transmitter fault (loop out of range) on TT-443 → `A_TT_FAIL`, heaters off, HMI shows last good value. Same pattern for LT-444 / PT-445. |
| 6.8 | `TANK_TEMP` > SP + 10 °C → `A_TEMP_HIGH` (critical). |

## 7. HMI / MES interface

Holding registers 0–7 (`%QW0..7`) are polled by the Ignition gateway every 1 s. `HMI_CYCLE_COUNT` is the source for the shift good-count on the L4 MES work-order screen; downtime reasons are derived from `HMI_STATE` ≠ 6 together with the first alarm bit set in `HMI_ALARMS`. Alarm text, priority and operator actions are in `Alarm-List-L4-WASH-01.csv`, which is also the import for the Ignition alarm journal.

Stack light (CS-0117): red = ABORTED or any critical; amber = HELD or any warning; green steady = EXECUTE, green flashing 1 Hz = IDLE ready.

## 8. Verification

Each numbered requirement in sections 4–6 has a corresponding test in `sil/test_fds_<section>_*.py`, executed against the compiled program with simulated time (`make test` in `sil/`). New requirements must add a row here and a test there in the same change.
