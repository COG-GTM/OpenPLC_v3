"""
Finding F4 (talon/SECURITY-SWARM.md section 4.4): the EtherNet/IP (ENIP/PCCC)
server is enabled by default in the shipped openplc.db although Line 4 has no
EtherNet/IP consumer. CWE-1188 / CWE-1327.

The shipped default must be 'disabled' (the convention already used for
Dnp3_port), the startup path must not start the ENIP server for that value,
and an operator must still be able to re-enable it through Settings.
"""
import re
import socket

import pytest

from conftest import SHIPPED_DB, get_setting, set_setting

webserver = pytest.importorskip("webserver")


class FakeRuntime:
    """Records the runtime RPCs configure_runtime() would issue to core/openplc."""

    def __init__(self):
        self.calls = []
        self.project_name = ""
        self.project_description = ""
        self.project_file = ""

    def status(self):
        return "Stopped"

    def __getattr__(self, name):
        if name.startswith(("start_", "stop_")):
            def record(*args):
                self.calls.append((name,) + args)
            return record
        raise AttributeError(name)


@pytest.fixture
def fake_runtime(monkeypatch):
    rt = FakeRuntime()
    monkeypatch.setattr(webserver, "openplc_runtime", rt)
    return rt


def test_shipped_db_has_enip_disabled():
    assert get_setting(SHIPPED_DB, "Enip_port") == "disabled"


def test_startup_does_not_start_enip_with_shipped_defaults(webserver_cwd, fake_runtime):
    webserver.configure_runtime()
    started = [c for c in fake_runtime.calls if c[0] == "start_enip"]
    assert started == [], f"ENIP server started at boot with shipped defaults: {started}"
    assert ("stop_enip",) in fake_runtime.calls


def test_startup_starts_enip_when_operator_enables_it(webserver_cwd, fake_runtime):
    set_setting(webserver_cwd, "Enip_port", "44818")
    webserver.configure_runtime()
    assert ("start_enip", 44818) in fake_runtime.calls


def _login(client):
    resp = client.post("/login", data={"username": "openplc", "password": "openplc"})
    assert resp.status_code == 302


def _enip_checkbox(html):
    m = re.search(r'<input id="enip_server" type="checkbox"([^>]*)>', html)
    assert m, "EtherNet/IP checkbox missing from settings page"
    return m.group(1)


def test_settings_page_shows_enip_unchecked_by_default(webserver_cwd, fake_runtime):
    client = webserver.app.test_client()
    _login(client)
    resp = client.get("/settings")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "checked" not in _enip_checkbox(html)
    assert "name='enip_server_port' value='44818'" in html


def test_operator_can_reenable_enip_from_settings(webserver_cwd, fake_runtime):
    client = webserver.app.test_client()
    _login(client)
    resp = client.post("/settings", data={
        "modbus_server": "true", "modbus_server_port": "502",
        "enip_server": "true", "enip_server_port": "44818",
        "slave_polling_period": "100", "slave_timeout": "1000",
        "device_hostname": socket.gethostname(),
    })
    assert resp.status_code == 302
    assert get_setting(webserver_cwd, "Enip_port") == "44818"
    html = client.get("/settings").get_data(as_text=True)
    assert "checked" in _enip_checkbox(html)
