"""Hermetic fixtures for the OpenPLC webserver security tests.

Every test runs against a throw-away copy of ``webserver/`` state (openplc.db,
st_files/, static/, active_program) inside a temp directory, with the process
cwd pointed there because webserver.py/openplc.py use relative paths. Nothing
here binds a network port and the compile script is never executed: the
subprocess launch inside ``openplc.runtime.compile_program`` is replaced by a
recorder so tests can assert *what* would have been compiled.
"""
import os
import shutil
import sqlite3
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
WEBSERVER_DIR = os.path.join(REPO_ROOT, 'webserver')

if WEBSERVER_DIR not in sys.path:
    sys.path.insert(0, WEBSERVER_DIR)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Temp copy of the webserver runtime state; cwd is switched into it."""
    root = tmp_path / 'webserver'
    root.mkdir()
    shutil.copy(os.path.join(WEBSERVER_DIR, 'openplc.db'), root / 'openplc.db')
    shutil.copytree(os.path.join(WEBSERVER_DIR, 'st_files'), root / 'st_files')
    (root / 'static').mkdir()
    (root / 'core').mkdir()
    (root / 'core' / 'debug.blank').write_text('')
    (root / 'scripts').mkdir()
    (root / 'active_program').write_text('blank_program.st\n')

    # A file that lives OUTSIDE st_files/ (a sibling directory, reachable as
    # st_files/../outside/) - the containment target for the traversal
    # assertions. It must never be read or compiled.
    outside = root / 'outside'
    outside.mkdir()
    (outside / 'evil.st').write_text('PROGRAM outside END_PROGRAM\n')

    monkeypatch.chdir(root)
    return {'root': root, 'outside': outside}


class _Recorder:
    def __init__(self):
        self.calls = []


@pytest.fixture
def compile_calls(sandbox, monkeypatch):
    """Records the argv of every compile_program.sh launch instead of running it."""
    import openplc

    rec = _Recorder()

    class _FakeProc:
        stdout = None

    def fake_popen(args, *a, **kw):
        rec.calls.append(list(args))
        return _FakeProc()

    monkeypatch.setattr(openplc.subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(openplc, 'NonBlockingStreamReader', lambda stream: None)
    return rec


@pytest.fixture
def webapp(sandbox, compile_calls):
    """webserver.py's Flask app, with exceptions turned into 500s (not raised)."""
    import webserver

    webserver.app.testing = False
    webserver.app.config['PROPAGATE_EXCEPTIONS'] = False
    webserver.openplc_runtime.runtime_status = 'Stopped'
    return webserver


@pytest.fixture
def client(webapp):
    """Test client logged in as the default openplc/openplc user."""
    c = webapp.app.test_client()
    resp = c.post('/login', data={'username': 'openplc', 'password': 'openplc'})
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/dashboard')
    return c


def programs_files(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        return [r[0] for r in conn.execute('SELECT File FROM Programs')]
    finally:
        conn.close()


def register_program(db_path, filename, name='test program'):
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            'INSERT INTO Programs (Name, Description, File, Date_upload) VALUES (?, ?, ?, ?)',
            (name, 'security test fixture', filename, 1700000000),
        )
        conn.commit()
    finally:
        conn.close()
