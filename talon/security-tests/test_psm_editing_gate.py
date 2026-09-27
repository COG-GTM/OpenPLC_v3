"""SECURITY-SWARM finding 2 / CVE-2021-31630 (CWE-94).

The Hardware page's PSM "custom code" box is written verbatim to
``core/psm/main.py`` and executed as Python by the runtime.  The Talon HIL
bench needs that capability, so it is not removed; instead it must be OFF by
default (``Settings.Psm_editing_enabled``), refuse writes while off, keep the
prebuilt driver selector working, and leave an attributable audit record for
every write once an operator has turned it on.

All requests are dispatched through the Flask test client against a sandbox
copy of the webserver's working files (see conftest.py).  No exploit payload
is involved: the "code" submitted is an inert comment line.
"""
import hashlib
import socket

from conftest import get_setting, layer_calls, set_setting, table_rows

SETTING = "Psm_editing_enabled"
MARKER = "# talon security regression test marker\n"


def _psm_code(sandbox):
    return (sandbox / "core" / "psm" / "main.py").read_text()


def _post_hardware(client, layer, code):
    return client.post(
        "/hardware",
        data={"hardware_layer": layer, "custom_layer_code": code},
        content_type="multipart/form-data",
    )


def test_setting_defaults_off_in_shipped_db(sandbox):
    value = get_setting(sandbox / "openplc.db", SETTING)
    assert value in (None, "false"), "PSM editing must ship disabled"


def test_psm_write_refused_when_editing_disabled(client, sandbox):
    original = _psm_code(sandbox)
    assert get_setting(sandbox / "openplc.db", SETTING) in (None, "false")

    resp = _post_hardware(client, "psm_linux", MARKER + original)

    assert resp.status_code == 403, resp.data[:200]
    assert b"disabled" in resp.data.lower()
    assert _psm_code(sandbox) == original, "core/psm/main.py must not be modified while editing is disabled"
    assert layer_calls(sandbox) == [], "hardware layer must not be switched on a refused request"
    assert table_rows(sandbox / "openplc.db", "Psm_audit") == []


def test_restore_route_refused_when_editing_disabled(client, sandbox):
    (sandbox / "core" / "psm" / "main.py").write_text(MARKER)

    resp = client.get("/restore_custom_hardware")

    assert resp.status_code == 403
    assert _psm_code(sandbox) == MARKER


def test_prebuilt_driver_switch_still_works_when_disabled(client, sandbox):
    original = _psm_code(sandbox)

    # Browsers submit textarea content with CRLF line endings; an unedited box
    # must not be treated as a PSM modification.
    resp = _post_hardware(client, "blank", original.replace("\r\n", "\n").replace("\n", "\r\n"))

    assert resp.status_code == 200
    assert b"compile-program?file=blank_program.st" in resp.data
    assert layer_calls(sandbox) == ["blank"]
    assert _psm_code(sandbox) == original


def test_hardware_page_renders_psm_code_read_only_when_disabled(client, sandbox):
    resp = client.get("/hardware")
    body = resp.data.decode()

    assert resp.status_code == 200
    assert 'name="custom_layer_code"' in body
    assert "readonly" in body.split('name="custom_layer_code"')[1].split(">")[0]
    assert "PSM hardware-layer code editing is disabled" in body


def test_psm_write_allowed_and_audited_when_enabled(client, sandbox):
    set_setting(sandbox / "openplc.db", SETTING, "true")
    original = _psm_code(sandbox)
    new_code = MARKER + original

    resp = _post_hardware(client, "psm_linux", new_code)

    assert resp.status_code == 200
    assert b"compile-program?file=blank_program.st" in resp.data
    assert _psm_code(sandbox) == new_code
    assert layer_calls(sandbox) == ["psm_linux"]

    audit = table_rows(sandbox / "openplc.db", "Psm_audit")
    assert len(audit) == 1, "exactly one audit record per PSM write"
    entry = audit[0]
    assert entry["username"] == "openplc"
    assert entry["action"] == "edit"
    assert entry["byte_length"] == len(new_code.encode("utf-8"))
    assert entry["sha256"] == hashlib.sha256(new_code.encode("utf-8")).hexdigest()
    assert entry["timestamp"]

    page = client.get("/hardware").data.decode()
    assert "readonly" not in page.split('name="custom_layer_code"')[1].split(">")[0]


def test_restore_allowed_and_audited_when_enabled(client, sandbox):
    set_setting(sandbox / "openplc.db", SETTING, "true")
    (sandbox / "core" / "psm" / "main.py").write_text(MARKER)
    pristine = (sandbox / "core" / "psm" / "main.original").read_text()

    resp = client.get("/restore_custom_hardware")

    assert resp.status_code == 302
    assert _psm_code(sandbox) == pristine
    audit = table_rows(sandbox / "openplc.db", "Psm_audit")
    assert [a["action"] for a in audit] == ["restore"]
    assert audit[0]["username"] == "openplc"


def test_settings_page_toggles_psm_editing(client, sandbox):
    page = client.get("/settings").data.decode()
    assert "Allow PSM hardware-layer code editing" in page
    assert '<input id="psm_editing" type="checkbox">' in page

    form = {
        "modbus_server_port": "502", "slave_polling_period": "100", "slave_timeout": "1000",
        "auto_run_text": "false", "snap7_run_text": "false", "psm_editing_text": "true",
        "device_hostname": socket.gethostname(),
    }
    resp = client.post("/settings", data=form, content_type="multipart/form-data")
    assert resp.status_code == 302
    assert get_setting(sandbox / "openplc.db", SETTING) == "true"
    assert '<input id="psm_editing" type="checkbox" checked>' in client.get("/settings").data.decode()

    form["psm_editing_text"] = "false"
    client.post("/settings", data=form, content_type="multipart/form-data")
    assert get_setting(sandbox / "openplc.db", SETTING) == "false"
