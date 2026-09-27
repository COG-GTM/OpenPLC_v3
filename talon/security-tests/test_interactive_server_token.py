"""
F5 -- the runtime interactive server (TCP 43628) must require a per-boot token.

CWE-306, CVSS 3.1 AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:H (7.1).

The real ``webserver/core/interactive_server.cpp`` is compiled against small
stubs (``harness/interactive_server_stubs.cpp``) and driven over loopback on
an ephemeral port. Only protocol-level responses and the stub side effects
are asserted -- nothing here touches a live runtime.
"""

import os
import re
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE = REPO_ROOT / "webserver" / "core"
SNAP7_WRAPPER = REPO_ROOT / "utils" / "snap7_src" / "wrapper"
HARNESS_SRC = Path(__file__).resolve().parent / "harness" / "interactive_server_stubs.cpp"

sys.path.insert(0, str(REPO_ROOT / "webserver"))
import openplc  # noqa: E402

CONTROL_COMMAND = "start_modbus(15020)"
AUTH_ERROR = "Error: authentication required"


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("interactive server harness did not start listening")


def _send(port, line, timeout=3.0):
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as s:
        s.sendall((line + "\n").encode())
        return s.recv(4096).decode()


@pytest.fixture(scope="module")
def harness_bin(tmp_path_factory):
    out = tmp_path_factory.mktemp("harness") / "interactive_server_harness"
    cmd = [
        "g++", "-std=gnu++11", "-pthread", "-fpermissive", "-w",
        "-I", str(CORE), "-I", str(CORE / "lib"), "-I", str(SNAP7_WRAPPER),
        str(CORE / "interactive_server.cpp"), str(HARNESS_SRC),
        "-o", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


class Harness:
    def __init__(self, binary, token_file):
        self.port = _free_port()
        self.token_file = token_file
        env = dict(os.environ, OPENPLC_CTL_TOKEN_FILE=str(token_file))
        self.proc = subprocess.Popen(
            [str(binary), str(self.port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
        )
        _wait_for_port(self.port)

    def token(self):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if self.token_file.exists():
                return self.token_file.read_text().strip()
            time.sleep(0.05)
        return None

    def send(self, line):
        return _send(self.port, line)

    def stop(self):
        token = self.token()
        if self.proc.poll() is None:
            try:
                _send(self.port, f"{token} quit()" if token else "quit()", timeout=1.0)
            except OSError:
                pass
        try:
            out, _ = self.proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            out, _ = self.proc.communicate()
        return out


@pytest.fixture
def harness(harness_bin, tmp_path):
    h = Harness(harness_bin, tmp_path / "openplc_ctl.token")
    yield h
    h.stop()


def test_unauthenticated_control_command_is_rejected(harness):
    reply = harness.send(CONTROL_COMMAND)
    out = harness.stop()

    assert reply.startswith(AUTH_ERROR), reply
    assert "STUB startServer" not in out, out
    assert "rejected" in out.lower(), out


def test_wrong_token_is_rejected(harness):
    token = harness.token()
    assert token, "runtime did not publish a token file"
    bad = ("0" if token[0] != "0" else "1") + token[1:]

    reply = harness.send(f"{bad} {CONTROL_COMMAND}")
    out = harness.stop()

    assert reply.startswith(AUTH_ERROR), reply
    assert "STUB startServer" not in out, out


def test_token_file_is_random_and_owner_only(harness_bin, tmp_path):
    h1 = Harness(harness_bin, tmp_path / "boot1.token")
    t1 = h1.token()
    h1.stop()
    h2 = Harness(harness_bin, tmp_path / "boot2.token")
    t2 = h2.token()
    mode = stat.S_IMODE(os.stat(h2.token_file).st_mode)
    h2.stop()

    assert t1 and t2, "runtime did not publish a token file"
    assert re.fullmatch(r"[0-9a-f]{64}", t1), t1
    assert re.fullmatch(r"[0-9a-f]{64}", t2), t2
    assert t1 != t2, "token must be regenerated on every boot"
    assert mode == 0o600, oct(mode)
    assert not h2.token_file.exists(), "token file must be removed on shutdown"


def test_authenticated_control_command_is_accepted(harness):
    token = harness.token()
    assert token, "runtime did not publish a token file"

    reply = harness.send(f"{token} {CONTROL_COMMAND}")
    exec_time = harness.send(f"{token} exec_time()")
    out = harness.stop()

    assert reply == "OK\n", reply
    assert exec_time.strip().isdigit(), exec_time
    assert "STUB startServer port=15020 protocol=0" in out, out
    assert "HARNESS exit" in out, out
    assert token not in out, "token must never be written to the runtime log"


def test_openplc_rpc_supplies_token(tmp_path, monkeypatch):
    token = "ab" * 32
    token_file = tmp_path / "openplc_ctl.token"
    token_file.write_text(token + "\n")
    monkeypatch.setenv("OPENPLC_CTL_TOKEN_FILE", str(token_file))

    received = []
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3.0)

    def serve():
        conn, _ = listener.accept()
        with conn:
            received.append(conn.recv(4096).decode())
            conn.sendall(b"OK\n")

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    monkeypatch.setattr(openplc, "INTERACTIVE_PORT", listener.getsockname()[1], raising=True)

    rt = openplc.runtime()
    rt.runtime_status = "Running"
    reply = rt.start_modbus(15020)
    t.join(3.0)
    listener.close()

    assert reply == "OK\n"
    assert received == [f"{token} {CONTROL_COMMAND}\n"], received
