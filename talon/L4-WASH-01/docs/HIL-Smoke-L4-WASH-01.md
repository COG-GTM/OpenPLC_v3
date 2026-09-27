# HIL smoke transcript — L4-WASH-01 (PW-430) Rev G

Real OpenPLC runtime (`webserver/core/openplc`, unmodified) + `hil/plant_model_psm.py` as the
PSM hardware layer, driven by `hil/hil_smoke.py` over the interactive server (43628) and
Modbus/TCP (15020). HR 0–7 are the HMI/MES status registers, HR 1024–1029 the setpoints
(`%MW0..5`). Pushbuttons and the E-stop are injected through `/tmp/pw430_faults.json`.

Setup (from `webserver/`):

```sh
./scripts/change_hardware_layer.sh psm_linux
cp ../talon/L4-WASH-01/hil/plant_model_psm.py core/psm/main.py
cp ../talon/L4-WASH-01/L4_WASH_01.st st_files/ && ./scripts/compile_program.sh L4_WASH_01.st
./core/openplc &                       # cwd must be webserver/ for the PSM layer
python3 ../talon/L4-WASH-01/hil/hil_smoke.py
```

The tank starts at ambient (21 °C); heating to the 55 °C default takes ~50 min of wall time,
so the bench writes `SP_TEMP_X10 = 200` and `SP_WASH_TIME_S = 20` through HR 1024/1026 the same
way the Ignition HMI would, which also exercises the runtime setpoint path end to end.

```text
[   0.10s] interactive server: OK
[   1.11s] fault file <- {}
[   1.11s] === 0. power-up: setpoint defaults (HR 1024-1029) and status ===
[   1.21s] HR1024-1029 {'SP_TEMP_X10': 550, 'SP_TEMP_HYST_X10': 20, 'SP_WASH_TIME_S': 90, 'SP_JAM_TIME_S': 8, 'SP_FILL_PCT_X10': 650, 'SP_BLOCKED_WARN_S': 60}
[   1.21s] HR0-7  state= 2 STOPPED   step= 0 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[   1.21s] === 1. supervisor setpoint writes (tank is at ambient; a 55 C soak is 50 min) ===
[   1.21s] HR1024 SP_TEMP_X10 <- 200
[   1.21s] HR1026 SP_WASH_TIME_S <- 20
[   1.71s] HR1024-1029 {'SP_TEMP_X10': 200, 'SP_TEMP_HYST_X10': 20, 'SP_WASH_TIME_S': 20, 'SP_JAM_TIME_S': 8, 'SP_FILL_PCT_X10': 650, 'SP_BLOCKED_WARN_S': 60}
[   1.71s] === 2. RESET -> IDLE, START -> EXECUTE ===
[   1.71s] fault file <- {"pulse": "reset"}
[   3.22s] fault file <- {}
[   4.42s] HR0-7  state= 4 IDLE      step= 0 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[   4.42s] fault file <- {"pulse": "start"}
[   5.93s] fault file <- {}
[   7.14s] HR0-7  state= 6 EXECUTE   step=20 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[   7.14s] === 3. full part cycle: index in (20), spray (30), index out (40), back to 10 ===
[   7.14s] HR0-7  state= 6 EXECUTE   step=20 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[   7.14s] HR0-7  state= 6 EXECUTE   step=20 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[  10.16s] HR0-7  state= 6 EXECUTE   step=30 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[  10.16s] HR0-7  state= 6 EXECUTE   step=30 alarms=0x0000 temp= 21.0C level= 78.0% press=0.00bar cycles=0 remain=  0s  
[  11.37s] HR0-7  state= 6 EXECUTE   step=30 alarms=0x0000 temp= 21.0C level= 78.0% press=3.13bar cycles=0 remain= 20s  
[  20.44s] HR0-7  state= 6 EXECUTE   step=30 alarms=0x0000 temp= 21.0C level= 77.9% press=4.20bar cycles=0 remain= 10s  
[  30.51s] HR0-7  state= 6 EXECUTE   step=40 alarms=0x0000 temp= 21.0C level= 77.8% press=4.20bar cycles=1 remain=  0s  
[  30.51s] HR0-7  state= 6 EXECUTE   step=40 alarms=0x0000 temp= 21.0C level= 77.8% press=4.20bar cycles=1 remain=  0s  
[  34.74s] HR0-7  state= 6 EXECUTE   step=10 alarms=0x0000 temp= 21.0C level= 77.8% press=0.02bar cycles=1 remain=  0s  
[  34.74s] HR0-7  state= 6 EXECUTE   step=10 alarms=0x0000 temp= 21.0C level= 77.8% press=0.02bar cycles=1 remain=  0s  <- one part washed
[  34.74s] HR1024-1029 {'SP_TEMP_X10': 200, 'SP_TEMP_HYST_X10': 20, 'SP_WASH_TIME_S': 20, 'SP_JAM_TIME_S': 8, 'SP_FILL_PCT_X10': 650, 'SP_BLOCKED_WARN_S': 60}
[  34.74s] === 4. E-stop via fault file while in EXECUTE ===
[  34.74s] fault file <- {"estop": true}
[  34.74s] HR0-7  state= 6 EXECUTE   step=10 alarms=0x0000 temp= 21.0C level= 77.8% press=0.02bar cycles=1 remain=  0s  
[  35.35s] HR0-7  state= 9 ABORTED   step= 0 alarms=0x0001 temp= 21.0C level= 77.8% press=0.01bar cycles=1 remain=  0s  
[  35.35s] HR0-7  state= 9 ABORTED   step= 0 alarms=0x0001 temp= 21.0C level= 77.8% press=0.01bar cycles=1 remain=  0s  <- ABORTED, alarm bit 0
[  37.35s] fault file <- {}
[  37.35s] HR0-7  state= 9 ABORTED   step= 0 alarms=0x0001 temp= 21.0C level= 77.8% press=0.00bar cycles=1 remain=  0s  
[  38.36s] HR0-7  state= 9 ABORTED   step= 0 alarms=0x0000 temp= 21.0C level= 77.8% press=0.00bar cycles=1 remain=  0s  
[  38.36s] fault file <- {"pulse": "reset"}
[  39.87s] fault file <- {}
[  41.07s] HR0-7  state= 2 STOPPED   step= 0 alarms=0x0000 temp= 21.0C level= 77.8% press=0.00bar cycles=1 remain=  0s  
[  41.07s] fault file <- {"pulse": "reset"}
[  42.58s] fault file <- {}
[  43.79s] HR0-7  state= 4 IDLE      step= 0 alarms=0x0000 temp= 21.0C level= 77.8% press=0.00bar cycles=1 remain=  0s  
[  43.79s] HR1024-1029 {'SP_TEMP_X10': 200, 'SP_TEMP_HYST_X10': 20, 'SP_WASH_TIME_S': 20, 'SP_JAM_TIME_S': 8, 'SP_FILL_PCT_X10': 650, 'SP_BLOCKED_WARN_S': 60}  (setpoints survive the abort)
[  43.79s] === HIL smoke PASSED ===
```
