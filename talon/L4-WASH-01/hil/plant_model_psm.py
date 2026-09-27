#                  - PW-430 plant model for the OpenPLC PSM hardware layer -
#
# Runs inside the OpenPLC runtime as its Python SubModule (Hardware > "Python on
# Linux (PSM)", paste this file). Instead of real I/O the runtime sees a physics
# model of the Cell 4-30 washer: a tank that heats and cools, a conveyor that
# carries blocks past three photoeyes, a contactor with a pull-in delay, and a
# spray header that builds pressure. The compiled L4_WASH_01 program is then
# exercised exactly as it would be on the machine, over the same %IX/%QX image,
# with the web HMI / Modbus server live - a hardware-in-the-loop bench without
# the hardware.
#
# Fault injection: drop a JSON file next to the runtime (default
# /tmp/pw430_faults.json) and it is re-read once a second, e.g.
#     {"estop": true}                    pull an E-stop
#     {"door_open": true}                open the chamber door
#     {"tank_leak_pct_s": 0.5}           tank drains at 0.5 %/s
#     {"contactor_stuck": true}          M2 aux stays made after the command drops
#     {"htr_trip": true}                 high-limit thermostat opens
#     {"tt_open_loop": true}             temperature transmitter wire break
#     {"jam": true}                      part stops short of the chamber beam
#     {"downstream_full": true}          Cell 4-40 stops taking parts
#     {"stop_pb": true}                  press the STOP pushbutton
#     {"pulse": "reset"} / {"pulse": "start"}   one-shot pushbutton presses
# An empty file (or {}) returns everything to normal. Setpoints (%MW0..5) are not
# I/O: write them the way the HMI does, through the runtime's Modbus/TCP server
# (holding registers 1024..1029, see docs/IO-List-L4-WASH-01.csv).

import json
import os
import time

import psm

CYCLE_S = 0.05                      # PSM loop period, matches the 50 ms PLC task
FAULT_FILE = os.environ.get("PW430_FAULTS", "/tmp/pw430_faults.json")

RAW_SPAN = 27648.0
OPEN_LOOP = -32768                  # 0 mA -> below the FB_SCALE_AI low limit


def raw(eu, lo, hi):
    return int(max(-32768, min(32767, (eu - lo) / (hi - lo) * RAW_SPAN)))


class Tank:
    """1,500 L wash tank, 3 x 18 kW immersion elements, steel shell losses."""
    def __init__(self):
        self.temp_c = 21.0
        self.level_pct = 78.0

    def step(self, dt, heater_on, fill_on, pump_on, leak_pct_s):
        volume_l = 1500.0 * max(self.level_pct, 5.0) / 100.0
        p_heat = 54_000.0 if heater_on else 0.0
        p_loss = 900.0 * (self.temp_c - 21.0) / 30.0      # ~900 W at 51 C
        p_spray = 2_500.0 if pump_on else 0.0             # cold block + evaporation
        self.temp_c += (p_heat - p_loss - p_spray) * dt / (volume_l * 4186.0)

        self.level_pct += (0.35 if fill_on else 0.0) * dt
        self.level_pct -= (0.012 if pump_on else 0.0) * dt  # carry-out / mist
        self.level_pct -= leak_pct_s * dt
        self.level_pct = max(0.0, min(100.0, self.level_pct))


class Conveyor:
    """Chain conveyor, 0.22 m/s. Photoeyes at fixed positions along the chain."""
    PE_INFEED = (0.00, 0.35)     # block occupies ~0.35 m
    PE_CHAMBER = (1.60, 1.95)
    PE_OUTFEED = (3.10, 3.45)
    SPEED = 0.22
    BLOCK_LEN = 0.60

    def __init__(self):
        self.blocks = [0.0]          # leading-edge positions, one block staged
        self.next_arrival_s = 90.0

    def _sees(self, pe):
        lo, hi = pe
        return any(x + self.BLOCK_LEN > lo and x < hi for x in self.blocks)

    def step(self, dt, running, jam, downstream_full):
        if running:
            for i, x in enumerate(self.blocks):
                nx = x + self.SPEED * dt
                if jam and x < 1.30 <= nx:
                    nx = 1.30                            # hung up on the guide rail
                self.blocks[i] = nx
        # downstream takes finished blocks away unless Cell 4-40 is full
        self.blocks = [x for x in self.blocks if x < 3.45 or downstream_full]
        if downstream_full:
            self.blocks = [min(x, 3.10) for x in self.blocks]
        # upstream delivers a new block every ~2 min once the infeed is clear
        if not self._sees(self.PE_INFEED):
            self.next_arrival_s -= dt
            if self.next_arrival_s <= 0.0:
                self.blocks.insert(0, 0.0)
                self.next_arrival_s = 120.0

    def photoeyes(self):
        return self._sees(self.PE_INFEED), self._sees(self.PE_CHAMBER), self._sees(self.PE_OUTFEED)


class Pump:
    """M2 contactor (pull-in / drop-out delay) and spray header pressure."""
    def __init__(self):
        self.aux = False
        self.cmd_since = None
        self.press_bar = 0.0

    def step(self, dt, cmd, stuck):
        now = time.monotonic()
        if cmd != (self.cmd_since is not None and self.cmd_since[0]):
            self.cmd_since = (cmd, now)
        if self.cmd_since and now - self.cmd_since[1] > 0.15:
            self.aux = cmd or stuck
        target = 4.2 if self.aux else 0.0
        self.press_bar += (target - self.press_bar) * min(1.0, dt / 0.8)


class Plant:
    def __init__(self):
        self.tank = Tank()
        self.conv = Conveyor()
        self.pump = Pump()
        self.faults = {}
        self.pulse_until = {}
        self.last_fault_read = 0.0
        self.last_t = time.monotonic()

    def read_faults(self):
        now = time.monotonic()
        if now - self.last_fault_read < 1.0:
            return
        self.last_fault_read = now
        try:
            with open(FAULT_FILE) as fh:
                new = json.load(fh) or {}
        except (OSError, ValueError):
            new = {}
        pulse = new.pop("pulse", None)
        if pulse and pulse != self.faults.get("_last_pulse"):
            self.pulse_until[pulse] = now + 0.3
            new["_last_pulse"] = pulse
        elif "_last_pulse" in self.faults and pulse:
            new["_last_pulse"] = pulse
        self.faults = new

    def f(self, key, default=False):
        return self.faults.get(key, default)

    def pressed(self, name):
        return time.monotonic() < self.pulse_until.get(name, 0.0)

    def step(self):
        now = time.monotonic()
        dt = min(now - self.last_t, 0.25)
        self.last_t = now
        self.read_faults()

        heater_on = bool(psm.get_var("QX0.2"))
        fill_on = bool(psm.get_var("QX0.3"))
        infeed_run = bool(psm.get_var("QX0.0"))
        pump_cmd = bool(psm.get_var("QX0.1"))

        # the hard-wired safety circuit drops the pump/heater regardless of the PLC
        estop = self.f("estop")
        self.pump.step(dt, pump_cmd and not estop, self.f("contactor_stuck"))
        self.tank.step(dt, heater_on and not estop and not self.f("htr_trip"),
                       fill_on, self.pump.aux, float(self.f("tank_leak_pct_s", 0.0)))
        self.conv.step(dt, infeed_run and not estop, self.f("jam"), self.f("downstream_full"))
        pe_in, pe_ch, pe_out = self.conv.photoeyes()

        psm.set_var("IX0.0", not estop)
        psm.set_var("IX0.1", not self.f("door_open"))
        psm.set_var("IX0.2", self.pressed("reset"))
        psm.set_var("IX0.3", self.pressed("start"))
        psm.set_var("IX0.4", not self.f("stop_pb"))
        psm.set_var("IX0.5", not self.f("manual"))
        psm.set_var("IX0.6", pe_in)
        psm.set_var("IX0.7", pe_ch)
        psm.set_var("IX1.0", pe_out)
        psm.set_var("IX1.1", self.tank.level_pct > 15.0)
        psm.set_var("IX1.2", self.tank.level_pct > 95.0)
        psm.set_var("IX1.3", self.pump.aux)
        psm.set_var("IX1.4", not self.f("vfd_fault"))
        psm.set_var("IX1.5", not self.f("pump_ol"))
        psm.set_var("IX1.6", not self.f("htr_trip"))

        psm.set_var("IW0", OPEN_LOOP if self.f("tt_open_loop") else raw(self.tank.temp_c, 0.0, 100.0))
        psm.set_var("IW1", OPEN_LOOP if self.f("lt_open_loop") else raw(self.tank.level_pct, 0.0, 100.0))
        psm.set_var("IW2", raw(self.pump.press_bar, 0.0, 10.0))


plant = Plant()


def hardware_init():
    psm.start()


def update_inputs():
    plant.step()


def update_outputs():
    pass


if __name__ == "__main__":
    hardware_init()
    while not psm.should_quit():
        update_inputs()
        update_outputs()
        time.sleep(CYCLE_S)
