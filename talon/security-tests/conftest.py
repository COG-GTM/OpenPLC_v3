"""Shared fixtures for the Talon OT security regression tests.

The REST API (webserver/restapi.py) reads its database URI, JWT secret and
password pepper from the environment via webserver/config.py, which will
generate a repo-root .env (and delete an existing restapi.db) when those are
missing.  Point everything at a per-session temporary directory *before* the
module is imported so the tests never touch the deployed database or .env.
"""
import os
import secrets
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBSERVER = REPO_ROOT / "webserver"
ENV_FILE = REPO_ROOT / ".env"

_TMP = tempfile.TemporaryDirectory(prefix="talon-sec-")
os.environ["FLASK_ENV"] = "development"
os.environ["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{_TMP.name}/restapi.db"
os.environ["JWT_SECRET_KEY"] = secrets.token_hex(32)
os.environ["PEPPER"] = secrets.token_hex(32)

_created_env_file = False
if not ENV_FILE.exists():
    # config.py unconditionally writes .env when absent; pre-seed it with the
    # same throwaway values so nothing outside the temp dir is modified.
    ENV_FILE.write_text(
        "FLASK_ENV=development\n"
        f"SQLALCHEMY_DATABASE_URI={os.environ['SQLALCHEMY_DATABASE_URI']}\n"
        f"JWT_SECRET_KEY={os.environ['JWT_SECRET_KEY']}\n"
        f"PEPPER={os.environ['PEPPER']}\n"
    )
    _created_env_file = True

if str(WEBSERVER) not in sys.path:
    sys.path.insert(0, str(WEBSERVER))


def pytest_sessionfinish(session, exitstatus):
    if _created_env_file and ENV_FILE.exists():
        ENV_FILE.unlink()
    _TMP.cleanup()


@pytest.fixture(scope="session")
def restapi():
    import restapi as mod

    mod.app_restapi.config["TESTING"] = True
    mod.app_restapi.register_blueprint(mod.restapi_bp, url_prefix="/api")
    with mod.app_restapi.app_context():
        mod.db.create_all()
    return mod


@pytest.fixture
def fresh_db(restapi):
    """Empty User table before and after each test."""
    with restapi.app_restapi.app_context():
        restapi.db.drop_all()
        restapi.db.create_all()
        restapi.jwt_blacklist.clear()
    yield restapi
    with restapi.app_restapi.app_context():
        restapi.db.session.remove()
        restapi.db.drop_all()
