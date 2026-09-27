"""Shared fixtures for the Talon OT security regression tests.

Tests import the runtime's web server modules straight from ``webserver/``
and run every request against a temporary copy of the shipped
``webserver/openplc.db`` so nothing touches the checked-in database.
"""
import importlib
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBSERVER_DIR = REPO_ROOT / "webserver"
SHIPPED_DB = WEBSERVER_DIR / "openplc.db"

if str(WEBSERVER_DIR) not in sys.path:
    sys.path.insert(0, str(WEBSERVER_DIR))


@pytest.fixture
def db_copy(tmp_path):
    """Temp copy of the shipped openplc.db; yields its path."""
    dst = tmp_path / "openplc.db"
    shutil.copyfile(SHIPPED_DB, dst)
    return dst


@pytest.fixture
def db_conn(db_copy):
    conn = sqlite3.connect(str(db_copy))
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def webserver_module():
    """Import ``webserver.py`` once (importing does not start any listener)."""
    return importlib.import_module("webserver")


@pytest.fixture
def client(webserver_module, db_copy, monkeypatch):
    """Flask test client whose ``openplc.db`` resolves to the temp copy."""
    monkeypatch.chdir(db_copy.parent)
    app = webserver_module.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
