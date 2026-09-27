"""
SECURITY-SWARM finding 6 (CWE-319 / CWE-330 / CWE-614): the legacy web UI
regenerated its Flask session secret with os.urandom() on every start, so
sessions were silently invalidated on each runtime restart and the secret was
never persisted, reviewed or permission-protected.  The session cookie also
carried no SameSite attribute and there was no way to mark it Secure for a
TLS-terminated deployment.

These tests drive webserver.py's Flask app (no live listener) and a temp copy
of openplc.db.  They fail on the unpatched tree and pass with the fix.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import flask
import pytest

from conftest import REPO_ROOT, WEBSERVER_DIR

HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture()
def env_file(tmp_path):
    return tmp_path / ".env"


@pytest.fixture()
def webserver_cwd(tmp_path, monkeypatch):
    """Run the web app against a throwaway copy of openplc.db."""
    workdir = tmp_path / "webserver"
    workdir.mkdir()
    shutil.copy(WEBSERVER_DIR / "openplc.db", workdir / "openplc.db")
    monkeypatch.chdir(workdir)
    return workdir


def _import_webserver(env_path):
    import config
    config.ENV_PATH = Path(env_path)
    sys.modules.pop("webserver", None)
    import webserver
    return webserver


def _app_secret_in_fresh_process(env_path):
    """Boot webserver.py in a brand-new interpreter (i.e. a runtime restart)
    and report the session secret it ends up with."""
    code = (
        "import sys, pathlib\n"
        "import config\n"
        f"config.ENV_PATH = pathlib.Path({str(env_path)!r})\n"
        "import webserver\n"
        "print('SECRET=' + str(webserver.app.secret_key))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=WEBSERVER_DIR,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("SECRET="):
            return line[len("SECRET="):]
    raise AssertionError(f"no secret reported; stdout={proc.stdout!r}")


def test_secret_key_survives_runtime_restart(env_file):
    first = _app_secret_in_fresh_process(env_file)
    second = _app_secret_in_fresh_process(env_file)

    assert first == second, "session secret must not change between runtime starts"
    assert HEX64.match(first), "secret must be a managed 256-bit hex token, not str(os.urandom(16))"
    assert first != str(os.urandom(16))

    assert env_file.is_file()
    assert f"SECRET_KEY={first}" in env_file.read_text()
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_secret_key_is_appended_to_existing_env_without_clobbering(env_file):
    import config

    env_file.write_text(
        "FLASK_ENV=development\n"
        "JWT_SECRET_KEY=" + "a" * 64 + "\n"
        "PEPPER=" + "b" * 64 + "\n"
    )

    key = config.ensure_secret_key(env_file)
    again = config.ensure_secret_key(env_file)

    assert key == again
    text = env_file.read_text()
    assert "JWT_SECRET_KEY=" + "a" * 64 in text
    assert "PEPPER=" + "b" * 64 in text
    assert text.count("SECRET_KEY=" + key) == 1


def test_session_cookie_hardened_on_http_bench(env_file, webserver_cwd):
    webserver = _import_webserver(env_file)
    app = webserver.app

    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    # plaintext bench (Ignition / HIL) must keep working: Secure stays off by default
    assert app.config["SESSION_COOKIE_SECURE"] is False

    client = app.test_client()
    resp = client.post("/login", data={"username": "openplc", "password": "openplc"})
    assert resp.status_code == 302
    cookie = resp.headers.get("Set-Cookie", "")
    assert "session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Secure" not in cookie


def test_session_cookie_secure_when_tls_enabled(env_file, webserver_cwd):
    import config

    webserver = _import_webserver(env_file)
    app = webserver.app

    env_file.write_text("SESSION_COOKIE_SECURE=true\n")
    config.apply_session_security(app, env_file)

    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert HEX64.match(app.secret_key)

    client = app.test_client()
    resp = client.post("/login", data={"username": "openplc", "password": "openplc"})
    assert resp.status_code == 302
    cookie = resp.headers.get("Set-Cookie", "")
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_https_redirect_is_opt_in(env_file, webserver_cwd):
    import config

    webserver = _import_webserver(env_file)
    app = webserver.app

    assert app.config["FORCE_HTTPS_REDIRECT"] is False
    assert app.test_client().get("/login").status_code == 200

    env_file.write_text("FORCE_HTTPS_REDIRECT=true\n")
    config.apply_session_security(app, env_file)
    client = app.test_client()

    resp = client.get("/login")
    assert resp.status_code == 301
    assert resp.headers["Location"].startswith("https://")

    resp = client.get("/login", headers={"X-Forwarded-Proto": "https"})
    assert resp.status_code == 200
