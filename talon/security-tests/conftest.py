import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBSERVER_DIR = REPO_ROOT / "webserver"

if str(WEBSERVER_DIR) not in sys.path:
    sys.path.insert(0, str(WEBSERVER_DIR))


@pytest.fixture
def openplc_db(tmp_path):
    """Temp copy of the shipped openplc.db so tests never touch the real one."""
    db_copy = tmp_path / "openplc.db"
    shutil.copy(WEBSERVER_DIR / "openplc.db", db_copy)
    return db_copy


@pytest.fixture
def webserver_cwd(openplc_db, monkeypatch):
    """webserver.py opens 'openplc.db' relative to the CWD; point it at the temp copy."""
    monkeypatch.chdir(openplc_db.parent)
    for name in ("pages", "monitoring", "openplc", "restapi", "config", "credentials"):
        monkeypatch.syspath_prepend(str(WEBSERVER_DIR))
    return openplc_db
