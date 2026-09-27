"""Shared fixtures for the Talon OT security regression tests.

Every test runs the OpenPLC Flask webserver in-process (Flask test client, no
listening socket) against a throw-away sandbox directory that mirrors the
files ``webserver.py`` touches through relative paths: ``openplc.db``,
``active_program``, ``core/psm/main.py`` and ``scripts/``.  The real
``change_hardware_layer.sh`` is replaced by a stub that only records its
argument, so nothing is compiled and the repository checkout is never
modified.
"""
import os
import shutil
import sqlite3
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBSERVER_DIR = REPO_ROOT / "webserver"

if str(WEBSERVER_DIR) not in sys.path:
    sys.path.insert(0, str(WEBSERVER_DIR))

DEFAULT_USER = ("openplc", "openplc")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Temp copy of the webserver working directory; chdir'd for the test."""
    shutil.copy(WEBSERVER_DIR / "openplc.db", tmp_path / "openplc.db")
    (tmp_path / "active_program").write_text("blank_program.st\n")

    psm_dir = tmp_path / "core" / "psm"
    psm_dir.mkdir(parents=True)
    shutil.copy(WEBSERVER_DIR / "core" / "psm" / "main.py", psm_dir / "main.py")
    shutil.copy(WEBSERVER_DIR / "core" / "psm" / "main.original", psm_dir / "main.original")

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "openplc_driver").write_text("psm_linux\n")
    stub = scripts / "change_hardware_layer.sh"
    stub.write_text("#!/bin/sh\necho \"$1\" >> ./scripts/change_hardware_layer.calls\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def webserver_module(sandbox):
    import webserver  # noqa: WPS433  (import after sys.path / cwd are set)

    webserver.app.config["TESTING"] = True
    return webserver


@pytest.fixture
def client(webserver_module):
    """Flask test client already logged in as the shipped default user."""
    with webserver_module.app.test_client() as c:
        resp = c.post("/login", data={"username": DEFAULT_USER[0], "password": DEFAULT_USER[1]})
        assert resp.status_code in (200, 302)
        yield c


def set_setting(db_path, key, value):
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT OR REPLACE INTO Settings (Key, Value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_setting(db_path, key):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT Value FROM Settings WHERE Key = ?", (key,)).fetchone()
    conn.close()
    return None if row is None else row[0]


def table_rows(db_path, table):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return rows


def layer_calls(sandbox):
    calls = sandbox / "scripts" / "change_hardware_layer.calls"
    return calls.read_text().split() if calls.exists() else []
