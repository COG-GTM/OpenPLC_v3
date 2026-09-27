import os
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
    """Temp copy of the shipped openplc.db; the shipped file is never written."""
    dst = tmp_path / "openplc.db"
    shutil.copy(SHIPPED_DB, dst)
    return dst


@pytest.fixture
def webserver_cwd(db_copy, monkeypatch):
    """webserver.py opens 'openplc.db' relative to cwd; point cwd at the temp copy."""
    monkeypatch.chdir(db_copy.parent)
    return db_copy


def set_setting(db_path, key, value):
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE Settings SET Value = ? WHERE Key = ?", (value, key))
    conn.commit()
    conn.close()


def get_setting(db_path, key):
    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT Value FROM Settings WHERE Key = ?", (key,)).fetchone()
    conn.close()
    return None if row is None else row[0]
