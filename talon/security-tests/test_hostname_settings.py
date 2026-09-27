"""F8 — Settings page invoked `hostnamectl set-hostname` (as root) with an
unvalidated web-form value. CWE-20 / CWE-250.

Asserts that (a) malformed hostnames are rejected before any privileged call,
(b) valid RFC-1123 hostnames are accepted, and (c) the OS rename only happens
when the `Os_hostname_sync` setting is enabled.
"""

import sqlite3
import subprocess

import pytest

import device_hostname as dh

INVALID_HOSTNAMES = [
    "",
    "a" * 64,                      # single label longer than 63 chars
    "-leading",
    "trailing-",
    "a b",
    "foo;bar",
    "../x",
    "host name.local",
    "under_score",
    "a" * 60 + "." + "b" * 60 + "." + "c" * 60 + "." + "d" * 60 + "." + "e" * 20,  # > 253 total
    " padded ",
    None,
]

VALID_HOSTNAMES = ["pw-430", "L4-WASH-01", "l4-wash-01.kingsport.talon.local", "a", "x" * 63]


class Recorder:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, argv, *args, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode)


@pytest.fixture
def no_real_subprocess(monkeypatch):
    """Belt and braces: if anything reaches subprocess.run the test fails."""
    def forbidden(*args, **kwargs):
        raise AssertionError("subprocess.run must not be reached: %r" % (args,))
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(dh.subprocess, "run", forbidden)


# --- validation -------------------------------------------------------------

@pytest.mark.parametrize("bad", INVALID_HOSTNAMES, ids=repr)
def test_invalid_hostname_rejected_without_touching_os(bad, no_real_subprocess):
    run = Recorder()
    with pytest.raises(dh.InvalidHostname):
        dh.apply_device_hostname(bad, os_sync_enabled=True, current_hostname="old-name", run=run)
    assert run.calls == []


@pytest.mark.parametrize("good", VALID_HOSTNAMES)
def test_valid_rfc1123_hostname_accepted(good):
    assert dh.validate_device_hostname(good) == good


# --- gate --------------------------------------------------------------------

def test_gate_off_persists_but_never_calls_hostnamectl(no_real_subprocess):
    run = Recorder()
    change = dh.apply_device_hostname("pw-430", os_sync_enabled=False, current_hostname="old-name", run=run)
    assert change.hostname == "pw-430"
    assert change.os_changed is False
    assert "not changed" in change.message
    assert run.calls == []


def test_gate_on_calls_hostnamectl_with_validated_value(no_real_subprocess):
    run = Recorder()
    change = dh.apply_device_hostname("pw-430", os_sync_enabled=True, current_hostname="old-name", run=run)
    assert change.os_changed is True
    assert run.calls == [["hostnamectl", "set-hostname", "pw-430"]]


def test_gate_on_but_hostname_unchanged_is_a_noop(no_real_subprocess):
    run = Recorder()
    change = dh.apply_device_hostname("pw-430", os_sync_enabled=True, current_hostname="pw-430", run=run)
    assert change.os_changed is False
    assert run.calls == []


def test_gate_on_hostnamectl_failure_is_reported_not_hidden(no_real_subprocess):
    run = Recorder(returncode=1)
    change = dh.apply_device_hostname("pw-430", os_sync_enabled=True, current_hostname="old-name", run=run)
    assert change.os_changed is False
    assert "hostnamectl failed" in change.message


def test_gate_on_rejects_hostname_longer_than_host_name_max(no_real_subprocess):
    run = Recorder()
    fqdn = "a" * 63 + ".b"   # valid RFC-1123 (65 chars) but longer than Linux HOST_NAME_MAX
    assert dh.validate_device_hostname(fqdn) == fqdn
    with pytest.raises(dh.InvalidHostname):
        dh.apply_device_hostname(fqdn, os_sync_enabled=True, current_hostname="old-name", run=run)
    assert run.calls == []


# --- persistence ---------------------------------------------------------------

def test_settings_rows_default_to_gate_off(openplc_db):
    conn = sqlite3.connect(openplc_db)
    stored, os_sync = dh.read_hostname_settings(conn.cursor())
    assert stored is None
    assert os_sync is False


def test_settings_rows_round_trip(openplc_db):
    conn = sqlite3.connect(openplc_db)
    cur = conn.cursor()
    dh.write_hostname_settings(cur, "pw-430", False)
    conn.commit()
    assert dh.read_hostname_settings(cur) == ("pw-430", False)
    dh.write_hostname_settings(cur, "pw-431", True)
    conn.commit()
    assert dh.read_hostname_settings(cur) == ("pw-431", True)
    with pytest.raises(dh.InvalidHostname):
        dh.write_hostname_settings(cur, "foo;bar", True)
    assert dh.read_hostname_settings(cur) == ("pw-431", True)
