#!/usr/bin/env python3
"""HIL smoke for L4-WASH-01: drive the real runtime + PSM plant model through one part
cycle and one E-stop, logging the HMI registers (HR 0-7) and setpoints (HR 1024-1029).

Prerequisites (talon/README.md "Headless"): hardware layer psm_linux with
hil/plant_model_psm.py as core/psm/main.py, L4_WASH_01.st compiled, `./openplc` running.
Setpoints are written the way the Ignition HMI does - Modbus/TCP holding registers.

    python3 hil_smoke.py [--modbus-port 15020] [--faults /tmp/pw430_faults.json]
"""
import argparse
import json
import socket
import sys
import time

from pymodbus.client.sync import ModbusTcpClient

STATE = {1: "CLEARING", 2: "STOPPED", 3: "STARTING", 4: "IDLE", 6: "EXECUTE", 7: "STOPPING",
         8: "ABORTING", 9: "ABORTED", 10: "HOLDING", 11: "HELD", 15: "RESETTING"}
SP_NAMES = ("SP_TEMP_X10", "SP_TEMP_HYST_X10", "SP_WASH_TIME_S", "SP_JAM_TIME_S",
            "SP_FILL_PCT_X10", "SP_BLOCKED_WARN_S")
T0 = time.monotonic()


def log(msg):
    print(f"[{time.monotonic() - T0:7.2f}s] {msg}", flush=True)


def interactive(cmd, port=43628):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall((cmd + "\n").encode())
        return s.recv(1024).decode(errors="replace").strip()


def signed(v):
    return v - 65536 if v > 32767 else v


class Bench:
    def __init__(self, mb: ModbusTcpClient, faults_path: str):
        self.mb, self.faults_path = mb, faults_path
        self.faults = {}

    def fault(self, **kw):
        """Merge into the plant fault file (re-read by the model once a second)."""
        for k, v in kw.items():
            if v is None:
                self.faults.pop(k, None)
            else:
                self.faults[k] = v
        with open(self.faults_path, "w") as fh:
            json.dump(self.faults, fh)
        log(f"fault file <- {json.dumps(self.faults)}")

    def pulse(self, pb):
        """One-shot pushbutton; the model de-duplicates a repeated pulse until it has
        seen the file without one, and it polls the file once a second."""
        self.fault(pulse=pb)
        time.sleep(1.5)
        self.fault(pulse=None)
        time.sleep(1.2)

    def hmi(self):
        rr = self.mb.read_holding_registers(0, 8, unit=1)
        assert not rr.isError(), rr
        r = [signed(v) for v in rr.registers]
        return dict(state=r[0], step=r[1], alarms=r[2], temp=r[3] / 10, level=r[4] / 10,
                    press=r[5] / 100, cycles=r[6], remain=r[7])

    def setpoints(self):
        rr = self.mb.read_holding_registers(1024, 6, unit=1)
        assert not rr.isError(), rr
        return dict(zip(SP_NAMES, [signed(v) for v in rr.registers]))

    def write_sp(self, name, value):
        addr = 1024 + SP_NAMES.index(name)
        assert not self.mb.write_register(addr, value & 0xFFFF, unit=1).isError()
        log(f"HR{addr} {name} <- {value}")

    def show(self, note=""):
        h = self.hmi()
        log(f"HR0-7  state={h['state']:>2} {STATE.get(h['state'], '?'):<9} step={h['step']:>2} "
            f"alarms=0x{h['alarms'] & 0xFFFF:04X} temp={h['temp']:5.1f}C level={h['level']:5.1f}% "
            f"press={h['press']:4.2f}bar cycles={h['cycles']} remain={h['remain']:>3}s  {note}")
        return h

    def wait_for(self, pred, timeout, what):
        end = time.monotonic() + timeout
        last = None
        while time.monotonic() < end:
            h = self.hmi()
            key = (h["state"], h["step"], h["alarms"])
            if key != last:
                self.show()
                last = key
            if pred(h):
                return h
            time.sleep(0.2)
        self.show()
        sys.exit(f"TIMEOUT waiting for {what}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modbus-port", type=int, default=15020)
    ap.add_argument("--faults", default="/tmp/pw430_faults.json")
    ap.add_argument("--wash-s", type=int, default=20)
    a = ap.parse_args()

    log("interactive server: " + interactive(f"start_modbus({a.modbus_port})"))
    time.sleep(1.0)
    mb = ModbusTcpClient("127.0.0.1", port=a.modbus_port)
    assert mb.connect(), "modbus connect"
    b = Bench(mb, a.faults)
    b.fault()                                   # {} -> plant healthy

    log("=== 0. power-up: setpoint defaults (HR 1024-1029) and status ===")
    log(f"HR1024-1029 {b.setpoints()}")
    b.wait_for(lambda h: h["state"] == 2, 5, "STOPPED at power-up")

    log("=== 1. supervisor setpoint writes (tank is at ambient; a 55 C soak is 50 min) ===")
    b.write_sp("SP_TEMP_X10", 200)              # 20.0 C so the ambient tank is 'at temperature'
    b.write_sp("SP_WASH_TIME_S", a.wash_s)
    time.sleep(0.5)
    log(f"HR1024-1029 {b.setpoints()}")

    log("=== 2. RESET -> IDLE, START -> EXECUTE ===")
    b.pulse("reset")
    b.wait_for(lambda h: h["state"] == 4, 5, "IDLE")
    b.pulse("start")
    b.wait_for(lambda h: h["state"] == 6 and h["step"] >= 10, 5, "EXECUTE")

    log("=== 3. full part cycle: index in (20), spray (30), index out (40), back to 10 ===")
    b.wait_for(lambda h: h["step"] == 20, 5, "step 20")
    b.wait_for(lambda h: h["step"] == 30, 15, "step 30")
    b.wait_for(lambda h: h["step"] == 30 and h["remain"] > 0 and h["press"] > 3.0, 10, "spraying")
    mid = b.wait_for(lambda h: h["remain"] <= a.wash_s // 2, a.wash_s, "half wash")
    b.wait_for(lambda h: h["step"] == 40, a.wash_s + 5, "step 40")
    b.wait_for(lambda h: h["step"] == 10 and h["cycles"] == 1, 30, "part out, cycle counted")
    b.show("<- one part washed")
    log(f"HR1024-1029 {b.setpoints()}")

    log("=== 4. E-stop via fault file while in EXECUTE ===")
    b.fault(estop=True)
    b.wait_for(lambda h: h["state"] == 9, 5, "ABORTED")
    b.show("<- ABORTED, alarm bit 0")
    time.sleep(2.0)
    b.fault(estop=None)
    b.wait_for(lambda h: h["state"] == 9 and h["alarms"] == 0, 5, "E-stop restored, still ABORTED")
    b.pulse("reset")
    b.wait_for(lambda h: h["state"] == 2, 5, "STOPPED after first RESET")
    b.pulse("reset")
    b.wait_for(lambda h: h["state"] == 4, 5, "IDLE after second RESET")
    log(f"HR1024-1029 {b.setpoints()}  (setpoints survive the abort)")
    log("=== HIL smoke PASSED ===")


if __name__ == "__main__":
    main()
