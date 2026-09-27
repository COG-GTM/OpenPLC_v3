import pathlib
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = REPO_ROOT / "webserver" / "core"
HERE = pathlib.Path(__file__).resolve().parent


def _compile(out, extra_flags):
    cmd = [
        "g++", "-std=gnu++11", "-O1", "-fPIC", "-shared", "-w", "-fpermissive",
        "-I", str(CORE), "-I", str(CORE / "lib"),
        *extra_flags,
        str(CORE / "modbus.cpp"), str(HERE / "modbus_harness.cpp"),
        "-o", str(out), "-lpthread",
    ]
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.fixture(scope="session")
def modbus_lib_path(tmp_path_factory):
    """Build webserver/core/modbus.cpp + the harness into a shared object.

    Tries the peer-aware dispatcher first; if the tree under test predates it,
    falls back to the legacy two-argument dispatcher so the assertions run (and
    fail) against the unpatched code instead of erroring out at compile time.
    """
    build = tmp_path_factory.mktemp("modbus_build")
    out = build / "libmodbus_harness.so"
    res = _compile(out, [])
    mode = "peer-aware"
    if res.returncode != 0:
        legacy = _compile(out, ["-DMB_LEGACY_DISPATCH"])
        if legacy.returncode != 0:
            pytest.fail("modbus harness failed to compile:\n" + res.stderr + legacy.stderr)
        mode = "legacy"
    print(f"\n[modbus harness] compiled {mode} dispatcher -> {out}")
    return out
