# Talon Power Systems — Kingsport Engine Plant controls on OpenPLC

This directory holds the plant-side content Talon keeps alongside the OpenPLC Runtime it runs on Line 4. The runtime itself (`webserver/`, `utils/`) is upstream OpenPLC v3 under GPLv3 and is unchanged; everything under `talon/` is ours.

```
talon/
├── L4-WASH-01/                 Cell 4-30 aqueous parts washer (PW-430)
│   ├── L4_WASH_01.st           IEC 61131-3 Structured Text program (PackML state model)
│   ├── docs/
│   │   ├── FDS-L4-WASH-01.md   Functional Design Specification, Rev F
│   │   ├── IO-List-L4-WASH-01.csv     tag / address / device / terminal / Modbus map
│   │   └── Alarm-List-L4-WASH-01.csv  alarm word bits, priorities, operator actions
│   ├── sil/                    Software-in-the-loop: compiled program + simulated time + pytest
│   └── hil/                    Hardware-in-the-loop: physics model for the runtime's PSM layer
└── SECURITY-SWARM.md           OT security review scope, peer incidents, CVE map, findings
```

## Build and run the controller program

Build the runtime once (`./install.sh linux` from the repo root — compiles MatIEC, libmodbus, the runtime), then either:

- **Web UI**: `./start_openplc.sh`, open `http://localhost:8080` (default user `openplc`/`openplc`), Programs → Upload `talon/L4-WASH-01/L4_WASH_01.st`, Launch. Modbus/TCP is on 502 (root) — the HMI/MES registers are HR 0–7 and setpoints HR 1024–1029 (see the IO list).
- **Headless**: from `webserver/`, `cp ../talon/L4-WASH-01/L4_WASH_01.st st_files/ && ./scripts/compile_program.sh L4_WASH_01.st`, then `cd core && ./openplc` and send `start_modbus(15020)` to the interactive server on 43628.

With no I/O attached the program sits in ABORTED (state 9) with alarm word 0x2305 — E-stop, tank low, pump overload, both transmitters, heater high-limit — which is exactly what an unwired controller should report.

## SIL — test the program without a PLC

```
cd talon/L4-WASH-01/sil
make            # iec2c -> Res0.c/Config0.c, glue_generator, builds build/libl4wash_sil.so
make test       # pytest: 20 FDS-numbered tests, ~30 ms
```

`openplc_sil.Plc` loads the compiled program, drives `%IX/%IW/%MW` by ST tag name (tag map is parsed from the `.st`, not duplicated), steps scans with simulated time (a 90 s wash runs in microseconds), and reads `%QX/%QW`. Tests are named after FDS sections (`test_fds_4_safety.py` ↔ FDS §4). Requires `g++`, `make`, `python3`, `pytest`, and a built runtime.

## HIL — run the real runtime against a plant model

`hil/plant_model_psm.py` is a PSM hardware layer (Hardware → "Python on Linux (PSM)", paste the file). It models the tank thermal mass, make-up water, a chain conveyor with three photoeyes, contactor pull-in delay and spray pressure, and exposes fault injection through `/tmp/pw430_faults.json` (E-stop, door, leak, jam, stuck contactor, high-limit trip, open-loop transmitter, downstream full, pushbutton pulses). The compiled program, web dashboard and Modbus server run unmodified — that is the point: the same binary, same I/O image, different plant.

## Using this with Devin

Typical asks, in the order they land:

1. *"Read `talon/L4-WASH-01/L4_WASH_01.st` and `docs/FDS-L4-WASH-01.md`. Which FDS requirements have no test in `sil/`? Add them."* — the fail-to-start/stop alarm half of §5.3, §6.8 (temp high) and the horn re-sound in §4.4 are intentionally untested.
2. *"Cell 4-40 is adding a second outfeed photoeye. Extend the FDS, IO list, program and SIL tests — one PR."*
3. *"Run the OT security review in `talon/SECURITY-SWARM.md`: confirm each finding against the code, prove it with a test, fix it in the runtime, keep `make -C talon/L4-WASH-01/sil test` green. One PR per finding."*

Commit messages need `feature` or `bug`; PR descriptions end with `Devin-Org: engineering`.
