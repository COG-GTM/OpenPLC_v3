"""
ctypes front end for build/libl4wash_sil.so.

Tags are addressed by the names used in the ST program and the IO list, not by
%IX/%QW addresses, so a test reads the way the FDS is written:

    plc = Plc()
    plc.healthy()                 # every permissive made, tank full and at temp
    plc.set("PE_INFEED", True)
    plc.run(seconds=1)
    assert plc.get("INFEED_RUN")

The tag -> location map is parsed from the located-variable declarations in the
ST source so it can never drift from the program that was compiled.
"""
from __future__ import annotations

import ctypes
import os
import re
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ST_FILE = HERE.parent / "L4_WASH_01.st"
LIB_FILE = HERE / "build" / "libl4wash_sil.so"

# 4-20 mA input scaled to 0..27648 counts (Siemens convention used at Kingsport)
RAW_SPAN = 27648.0

_LOCATED = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s+AT\s+%(?P<area>[IQM])(?P<size>[XW])"
    r"(?P<byte>\d+)(?:\.(?P<bit>\d))?\s*:\s*(?P<type>[A-Za-z]+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Location:
    area: str   # I, Q, M
    size: str   # X (bit) or W (16-bit word)
    byte: int
    bit: int | None
    type: str

    @property
    def address(self) -> str:
        base = f"%{self.area}{self.size}{self.byte}"
        return f"{base}.{self.bit}" if self.bit is not None else base


def parse_tag_map(st_file: Path = ST_FILE) -> dict[str, Location]:
    text = st_file.read_text()
    # strip (* ... *) comments so commented-out declarations are ignored
    text = re.sub(r"\(\*.*?\*\)", "", text, flags=re.DOTALL)
    tags: dict[str, Location] = {}
    for m in _LOCATED.finditer(text):
        tags[m.group("name").upper()] = Location(
            area=m.group("area"),
            size=m.group("size"),
            byte=int(m.group("byte")),
            bit=int(m.group("bit")) if m.group("bit") is not None else None,
            type=m.group("type").upper(),
        )
    if not tags:
        raise RuntimeError(f"no located variables found in {st_file}")
    return tags


class Plc:
    """One compiled program instance. Construct a fresh one per test."""

    def __init__(self, lib_file: Path = LIB_FILE, st_file: Path = ST_FILE):
        if not lib_file.exists():
            raise FileNotFoundError(f"{lib_file} missing - run `make` in {HERE}")
        self.tags = parse_tag_map(st_file)
        self._lib = ctypes.CDLL(os.fspath(lib_file))
        self._lib.sil_ticktime_ns.restype = ctypes.c_ulonglong
        self._lib.sil_time_ms.restype = ctypes.c_longlong
        self._lib.sil_tick.restype = ctypes.c_ulong
        self._lib.sil_init()
        self.scan_ms = self._lib.sil_ticktime_ns() / 1_000_000

    # ---- time -----------------------------------------------------------------
    def scan(self, n: int = 1) -> None:
        self._lib.sil_scan(ctypes.c_uint(n))

    def run(self, seconds: float = 0.0, ms: float = 0.0) -> None:
        """Advance simulated time, rounding up to whole scans."""
        total_ms = seconds * 1000.0 + ms
        n = int(-(-total_ms // self.scan_ms))  # ceil
        self.scan(max(n, 1))

    @property
    def time_ms(self) -> int:
        return int(self._lib.sil_time_ms())

    @property
    def tick(self) -> int:
        return int(self._lib.sil_tick())

    def reset(self) -> None:
        self._lib.sil_init()

    # ---- tag access -------------------------------------------------------------
    def _loc(self, tag: str) -> Location:
        try:
            return self.tags[tag.upper()]
        except KeyError:
            raise KeyError(f"{tag!r} is not a located variable in {ST_FILE.name}") from None

    def set(self, tag: str, value) -> None:
        loc = self._loc(tag)
        if loc.size == "X":
            if loc.area != "I":
                raise ValueError(f"{tag} is {loc.address}: only %IX bits can be forced from the SIL side")
            rc = self._lib.sil_set_ix(loc.byte, loc.bit, 1 if value else 0)
        elif loc.area == "I":
            rc = self._lib.sil_set_iw(loc.byte, int(value))
        elif loc.area == "M":
            rc = self._lib.sil_set_mw(loc.byte, int(value))
        else:
            raise ValueError(f"{tag} is {loc.address}: outputs are owned by the program")
        if rc != 0:
            raise RuntimeError(f"{tag} ({loc.address}) is not glued in the compiled program")

    def get(self, tag: str):
        loc = self._loc(tag)
        if loc.size == "X":
            fn = self._lib.sil_get_ix if loc.area == "I" else self._lib.sil_get_qx
            rc = fn(loc.byte, loc.bit)
            if rc < 0:
                raise RuntimeError(f"{tag} ({loc.address}) is not glued in the compiled program")
            return bool(rc)
        out = ctypes.c_int()
        fn = {"I": self._lib.sil_get_iw, "Q": self._lib.sil_get_qw, "M": self._lib.sil_get_mw}[loc.area]
        rc = fn(loc.byte, ctypes.byref(out))
        if rc != 0:
            raise RuntimeError(f"{tag} ({loc.address}) is not glued in the compiled program")
        return out.value

    def set_many(self, **tags) -> None:
        for tag, value in tags.items():
            self.set(tag, value)

    # ---- engineering-unit helpers -----------------------------------------------
    @staticmethod
    def raw(eu: float, eu_min: float, eu_max: float) -> int:
        """Engineering value -> 0..27648 transmitter counts."""
        return int(round((eu - eu_min) / (eu_max - eu_min) * RAW_SPAN))

    def set_temp_c(self, deg_c: float) -> None:
        self.set("TANK_TEMP_RAW", self.raw(deg_c, 0.0, 100.0))

    def set_level_pct(self, pct: float) -> None:
        self.set("TANK_LEVEL_RAW", self.raw(pct, 0.0, 100.0))
        self.set("LSL_TANK", pct > 15.0)
        self.set("LSH_TANK", pct > 95.0)

    def set_press_bar(self, bar: float) -> None:
        self.set("PUMP_PRESS_RAW", self.raw(bar, 0.0, 10.0))

    # ---- canned conditions ------------------------------------------------------
    def healthy(self, temp_c: float = 55.0, level_pct: float = 80.0) -> None:
        """Every permissive satisfied, machine in AUTO, no part present."""
        self.set_many(
            ESTOP_OK=True, GUARD_CLOSED=True, PB_RESET=False, PB_START=False,
            PB_STOP_NC=True, SEL_AUTO=True, PE_INFEED=False, PE_CHAMBER=False,
            PE_OUTFEED=False, PUMP_AUX=False, INFEED_VFD_RDY=True, PUMP_OL_OK=True,
            HTR_OK=True,
        )
        self.set_temp_c(temp_c)
        self.set_level_pct(level_pct)
        self.set_press_bar(0.0)

    def pulse(self, tag: str, scans: int = 2) -> None:
        """Momentary pushbutton: make, hold for `scans`, release, one settle scan."""
        self.set(tag, True)
        self.scan(scans)
        self.set(tag, False)
        self.scan(1)

    def follow_pump_aux(self) -> None:
        """Simulate the M2 contactor: aux follows the run command on the next scan."""
        self.set("PUMP_AUX", self.get("PUMP_RUN"))

    def state(self) -> int:
        return self.get("HMI_STATE")

    def seq(self) -> int:
        return self.get("HMI_STEP")

    def alarm(self, bit: int) -> bool:
        return bool(self.get("HMI_ALARMS") & (1 << bit))


# PackML state numbers (ISA-TR88.00.02) as written to HMI_STATE
CLEARING, STOPPED, STARTING, IDLE = 1, 2, 3, 4
EXECUTE, STOPPING, ABORTING, ABORTED = 6, 7, 8, 9
HOLDING, HELD, RESETTING = 10, 11, 15

# HMI_ALARMS bit numbers, see docs/Alarm-List-L4-WASH-01.csv
ALM = {
    "ESTOP": 0, "GUARD_OPEN": 1, "TANK_LOW": 2, "TANK_HIGH": 3, "TEMP_LOW": 4,
    "TEMP_HIGH": 5, "JAM": 6, "PUMP_FTS": 7, "PUMP_OL": 8, "VFD_FAULT": 9,
    "LT_FAIL": 10, "TT_FAIL": 11, "BLOCKED": 12, "HTR_HILIMIT": 13,
}
