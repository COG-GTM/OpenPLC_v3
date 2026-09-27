"""F8 — `/settings` POST handed the raw `device_hostname` form field to
`hostnamectl set-hostname` (run as root) with no validation and no opt-in.

These tests drive the real Flask route with the test client, a temp copy of
openplc.db and a recorded `subprocess.run`. They deliberately do not import
the new helper module so they run (and fail) against the unpatched tree.
"""

import sqlite3
import subprocess
from types import SimpleNamespace

import pytest


class Recorder:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, argv, *args, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode)


SETTINGS_FORM = {
    "modbus_server_port": "502",
    "enip_server_port": "44818",
    "auto_run_text": "false",
    "snap7_run_text": "true",
    "slave_polling_period": "100",
    "slave_timeout": "1000",
}


def hostname_rows(db_path):
    conn = sqlite3.connect(db_path)
    rows = dict(conn.execute("SELECT Key, Value FROM Settings WHERE Key IN ('Device_hostname', 'Os_hostname_sync')").fetchall())
    conn.close()
    return rows


@pytest.fixture
def client(webserver_cwd, monkeypatch):
    import webserver

    webserver.app.config["TESTING"] = True
    monkeypatch.setattr(webserver, "configure_runtime", lambda: None)
    monkeypatch.setattr(webserver, "generate_mbconfig", lambda: None)
    monkeypatch.setattr(webserver.monitor, "stop_monitor", lambda: None)
    monkeypatch.setattr(webserver.socket, "gethostname", lambda: "old-name")
    monkeypatch.setattr(webserver.flask_login, "current_user",
                        SimpleNamespace(is_authenticated=True, id="openplc", name="OpenPLC User", pict_file="None"))
    return webserver.app.test_client()


@pytest.fixture
def run(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(subprocess, "run", recorder)
    return recorder


@pytest.mark.parametrize("bad", ["", "a" * 64, "-leading", "trailing-", "a b", "foo;bar", "../x"], ids=repr)
def test_settings_post_rejects_invalid_hostname_with_400_and_no_hostnamectl(client, run, bad):
    resp = client.post("/settings", data=dict(SETTINGS_FORM, device_hostname=bad, hostname_os_sync="true"))

    assert resp.status_code == 400
    body = resp.data.split(b"<body>", 1)[1]
    assert b"Invalid hostname" in body and b"Back to Settings" in body
    assert run.calls == [], "hostnamectl must never see an unvalidated hostname"


def test_settings_post_gate_off_stores_hostname_without_hostnamectl(client, run, webserver_cwd):
    resp = client.post("/settings", data=dict(SETTINGS_FORM, device_hostname="pw-430"))

    assert resp.status_code == 302
    assert run.calls == []
    assert hostname_rows(webserver_cwd) == {"Device_hostname": "pw-430", "Os_hostname_sync": "false"}


def test_settings_post_gate_on_applies_validated_hostname(client, run, webserver_cwd):
    resp = client.post("/settings", data=dict(SETTINGS_FORM, device_hostname="pw-430", hostname_os_sync="true"))

    assert resp.status_code == 302
    assert run.calls == [["hostnamectl", "set-hostname", "pw-430"]]
    assert hostname_rows(webserver_cwd) == {"Device_hostname": "pw-430", "Os_hostname_sync": "true"}


def test_settings_get_shows_stored_hostname_and_gate_default_off(client, run):
    client.post("/settings", data=dict(SETTINGS_FORM, device_hostname="pw-430"))

    resp = client.get("/settings")

    assert resp.status_code == 200
    assert b"name='device_hostname' value='pw-430'" in resp.data
    assert b'name="hostname_os_sync" type="checkbox" value=\'true\'>' in resp.data
    assert run.calls == []
