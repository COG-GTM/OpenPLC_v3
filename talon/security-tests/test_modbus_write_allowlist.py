"""
F3 - Unauthenticated Modbus/TCP writes to Line 4 setpoints (CWE-306 / CWE-862).

Drives the runtime's Modbus frame processor (webserver/core/modbus.cpp) directly
through a small C harness. No sockets, no listeners: the peer address is handed
to the dispatcher exactly as server.cpp does after accept().

Expected behaviour with an allowlist file present:
  * FC 5/6/15/16 (writes) and FC 0x41-0x45 (debugger: force/trace) from a source
    that is NOT listed -> exception response ILLEGAL FUNCTION (0x01), no memory
    mutation
  * FC 3 (read) from the same source -> still served (Ignition poll must keep
    working)
  * a listed source (exact IP or CIDR) -> writes accepted as before
Expected behaviour with no allowlist file: legacy behaviour (all sources may
write), with a warning logged at Modbus start.
"""
import ctypes

import pytest

HR_SP_TEMP_X10 = 1024      # %MW0 - Talon wash temperature setpoint (x10 degC)
HR_SP_JAM_TIME_S = 1028    # %MW4

EXC_ILLEGAL_FUNCTION = 0x01

ATTACKER = "172.20.4.99"   # maintenance laptop drop TB-4-430 on the cell VLAN
IGNITION = "172.20.4.10"   # listed exactly
MES_NET = "10.10.7.3"      # inside the listed 10.10.0.0/16
ALLOWLIST = f"""# Line 4 Modbus write allowlist
{IGNITION}          # Ignition gateway
10.10.0.0/16        # plant DMZ
"""


def mbap(fc, pdu, tid=0x0001, uid=0xFF):
    body = bytes([uid, fc]) + pdu
    return tid.to_bytes(2, "big") + b"\x00\x00" + len(body).to_bytes(2, "big") + body


def fc3_read(addr, count):
    return mbap(3, addr.to_bytes(2, "big") + count.to_bytes(2, "big"))


def fc5_write_coil(addr, on):
    return mbap(5, addr.to_bytes(2, "big") + (b"\xff\x00" if on else b"\x00\x00"))


def fc6_write_register(addr, value):
    return mbap(6, addr.to_bytes(2, "big") + value.to_bytes(2, "big"))


def fc15_write_coils(addr, bits):
    return mbap(15, addr.to_bytes(2, "big") + len(bits).to_bytes(2, "big") + bytes([1]) + bytes([sum(b << i for i, b in enumerate(bits))]))


def fc16_write_registers(addr, values):
    data = b"".join(v.to_bytes(2, "big") for v in values)
    return mbap(16, addr.to_bytes(2, "big") + len(values).to_bytes(2, "big") + bytes([len(data)]) + data)


def fc42_debug_set(varidx, value):
    # varidx(2) flag(1) len(2) value(len) - "force variable"
    return mbap(0x42, varidx.to_bytes(2, "big") + b"\x01" + len(value).to_bytes(2, "big") + value)


def fc41_debug_info():
    return mbap(0x41, b"")


def fc45_debug_md5():
    return mbap(0x45, b"\xde\xad")


class Plc:
    def __init__(self, lib):
        self.lib = lib
        lib.harness_init.restype = None
        lib.harness_load_allowlist.argtypes = [ctypes.c_char_p]
        lib.harness_load_allowlist.restype = ctypes.c_int
        lib.harness_process.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p]
        lib.harness_process.restype = ctypes.c_int
        lib.harness_holding_reg.argtypes = [ctypes.c_int]
        lib.harness_holding_reg.restype = ctypes.c_uint16
        lib.harness_set_holding_reg.argtypes = [ctypes.c_int, ctypes.c_uint16]
        lib.harness_set_holding_reg.restype = None
        lib.harness_set_trace_calls.restype = ctypes.c_int
        lib.harness_init()

    def load_allowlist(self, path):
        return self.lib.harness_load_allowlist(str(path).encode())

    def request(self, frame, peer):
        buf = ctypes.create_string_buffer(bytes(frame), 1024)
        n = self.lib.harness_process(buf, len(frame), peer.encode())
        assert n > 0, f"dispatcher returned {n}"
        return bytes(buf.raw[:n])

    def hr(self, idx):
        return self.lib.harness_holding_reg(idx)

    def set_hr(self, idx, value):
        self.lib.harness_set_holding_reg(idx, value)

    def set_trace_calls(self):
        return self.lib.harness_set_trace_calls()


@pytest.fixture
def plc(modbus_lib_path):
    # A fresh dlopen per test would need dlclose bookkeeping; harness_init()
    # resets every buffer and counter instead.
    return Plc(ctypes.CDLL(str(modbus_lib_path)))


@pytest.fixture
def enforced(plc, tmp_path):
    path = tmp_path / "mbwrite_allow.list"
    path.write_text(ALLOWLIST)
    plc.load_allowlist(path)
    return plc


def assert_exception(resp, fc, code):
    assert resp[7] == (fc | 0x80), f"expected exception for FC {fc:#04x}, got FC byte {resp[7]:#04x}"
    assert resp[8] == code, f"expected exception code {code:#04x}, got {resp[8]:#04x}"
    assert int.from_bytes(resp[4:6], "big") == 3


# --------------------------------------------------------------------------- #
# Enforcement: an unlisted cell-VLAN host cannot write setpoints or force vars
# --------------------------------------------------------------------------- #

def test_fc6_write_register_rejected_from_unlisted_source(enforced):
    enforced.set_hr(HR_SP_TEMP_X10, 600)          # 60.0 degC
    resp = enforced.request(fc6_write_register(HR_SP_TEMP_X10, 950), ATTACKER)
    assert_exception(resp, 6, EXC_ILLEGAL_FUNCTION)
    assert enforced.hr(HR_SP_TEMP_X10) == 600, "setpoint was mutated by an unlisted source"


def test_fc16_write_multiple_registers_rejected_from_unlisted_source(enforced):
    enforced.set_hr(HR_SP_TEMP_X10, 600)
    enforced.set_hr(HR_SP_JAM_TIME_S, 30)
    resp = enforced.request(fc16_write_registers(HR_SP_TEMP_X10, [950, 0, 0, 0, 1]), ATTACKER)
    assert_exception(resp, 16, EXC_ILLEGAL_FUNCTION)
    assert enforced.hr(HR_SP_TEMP_X10) == 600
    assert enforced.hr(HR_SP_JAM_TIME_S) == 30


def test_fc42_debug_set_rejected_from_unlisted_source(enforced):
    resp = enforced.request(fc42_debug_set(0, b"\x00\x01"), ATTACKER)
    assert_exception(resp, 0x42, EXC_ILLEGAL_FUNCTION)
    assert enforced.set_trace_calls() == 0, "force/trace was executed for an unlisted source"


@pytest.mark.parametrize("frame,fc", [
    (fc5_write_coil(0, True), 5),
    (fc15_write_coils(0, [1, 0, 1]), 15),
    (fc41_debug_info(), 0x41),
    (fc45_debug_md5(), 0x45),
], ids=["fc5_write_coil", "fc15_write_coils", "fc41_debug_info", "fc45_debug_md5"])
def test_other_write_and_debug_codes_rejected_from_unlisted_source(enforced, frame, fc):
    assert_exception(enforced.request(frame, ATTACKER), fc, EXC_ILLEGAL_FUNCTION)


# --------------------------------------------------------------------------- #
# Reads stay open: the Ignition/HMI poll from the same unlisted host still works
# --------------------------------------------------------------------------- #

def test_fc3_read_still_served_to_unlisted_source(enforced):
    enforced.set_hr(HR_SP_TEMP_X10, 600)
    resp = enforced.request(fc3_read(HR_SP_TEMP_X10, 2), ATTACKER)
    assert resp[7] == 3
    assert resp[8] == 4                            # byte count
    assert int.from_bytes(resp[9:11], "big") == 600


# --------------------------------------------------------------------------- #
# Listed sources keep working: exact IP and CIDR match
# --------------------------------------------------------------------------- #

def test_listed_exact_ip_can_write(enforced):
    resp = enforced.request(fc6_write_register(HR_SP_TEMP_X10, 650), IGNITION)
    assert resp[7] == 6                            # echo, not an exception
    assert enforced.hr(HR_SP_TEMP_X10) == 650


def test_listed_cidr_can_write(enforced):
    resp = enforced.request(fc16_write_registers(HR_SP_TEMP_X10, [650, 30]), MES_NET)
    assert resp[7] == 16
    assert enforced.hr(HR_SP_TEMP_X10) == 650
    assert enforced.hr(HR_SP_TEMP_X10 + 1) == 30


def test_listed_source_can_use_debugger(enforced):
    resp = enforced.request(fc42_debug_set(0, b"\x00\x01"), IGNITION)
    assert resp[7] == 0x42 and resp[8] == 0x7E     # MB_DEBUG_SUCCESS
    assert enforced.set_trace_calls() == 1


# --------------------------------------------------------------------------- #
# Allowlist file handling
# --------------------------------------------------------------------------- #

def test_missing_allowlist_file_preserves_legacy_behaviour(plc, tmp_path):
    assert plc.load_allowlist(tmp_path / "does-not-exist.list") == -1
    resp = plc.request(fc6_write_register(HR_SP_TEMP_X10, 700), ATTACKER)
    assert resp[7] == 6
    assert plc.hr(HR_SP_TEMP_X10) == 700


def test_empty_allowlist_file_denies_all_writes(plc, tmp_path):
    path = tmp_path / "mbwrite_allow.list"
    path.write_text("# nobody may write\n")
    assert plc.load_allowlist(path) == 0
    assert_exception(plc.request(fc6_write_register(HR_SP_TEMP_X10, 700), IGNITION), 6, EXC_ILLEGAL_FUNCTION)
    assert plc.hr(HR_SP_TEMP_X10) == 0


def test_invalid_lines_are_skipped_not_fatal(plc, tmp_path):
    path = tmp_path / "mbwrite_allow.list"
    path.write_text("not-an-address\n172.20.4.10/33\n172.20.4.10\n")
    assert plc.load_allowlist(path) == 1
    assert plc.request(fc6_write_register(HR_SP_TEMP_X10, 1), IGNITION)[7] == 6
    assert_exception(plc.request(fc6_write_register(HR_SP_TEMP_X10, 1), ATTACKER), 6, EXC_ILLEGAL_FUNCTION)
