"""F7 - unvalidated ST filenames in the program upload/compile path.

CWE-22 (path traversal) / CWE-434 (unrestricted upload).
CVSS 3.1 AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H = 8.8.

The compile route takes ``?file=`` straight from the query string and
``openplc.runtime.compile_program`` concatenates it onto ``./st_files/``;
``/upload-program-action`` accepts the ``prog_file`` hidden field verbatim and
registers it in the Programs table, so an authenticated user controls both the
DB-side and the request-side name. These tests assert that every non-plain
name is rejected with a 400 before anything outside ``st_files/`` is touched or
handed to ``scripts/compile_program.sh``, while a legitimate registered
``<digits>.st`` still compiles. Picture uploads must take their extension from
the detected image type, not from the client filename.
"""
import io
import os
import re

import pytest

from conftest import programs_files, register_program

TRAVERSAL_NAMES = [
    '../../etc/passwd',
    '../x.st',
    '..%2Fx.st',
    '/etc/passwd',
    '/tmp/absolute.st',
    'blank_program.st/../../outside/evil.st',
    '..\\x.st',
    'blank_program.txt',
    '',
]

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
GIF_BYTES = b'GIF89a' + b'\x00' * 32


def _active_program(sandbox):
    return (sandbox['root'] / 'active_program').read_text()


# --------------------------------------------------------------------------
# /compile-program?file=<name>
# --------------------------------------------------------------------------

@pytest.mark.parametrize('name', TRAVERSAL_NAMES)
def test_compile_route_rejects_unsafe_names(client, sandbox, compile_calls, name):
    resp = client.get('/compile-program', query_string={'file': name})

    assert resp.status_code == 400, (name, resp.status_code)
    assert compile_calls.calls == []
    assert _active_program(sandbox) == 'blank_program.st\n'
    assert not (sandbox['root'] / 'core' / 'debug.cpp').exists()


def test_compile_route_rejects_url_encoded_traversal(client, compile_calls):
    # Werkzeug decodes %2F to '/', so the handler sees '../x.st'.
    resp = client.get('/compile-program?file=..%2Fx.st')
    assert resp.status_code == 400
    assert compile_calls.calls == []


def test_compile_route_rejects_unregistered_name(client, sandbox, compile_calls):
    # Well-formed name, present on disk, but not in the Programs table.
    (sandbox['root'] / 'st_files' / '424242.st').write_text('PROGRAM p END_PROGRAM\n')

    resp = client.get('/compile-program', query_string={'file': '424242.st'})

    assert resp.status_code == 400
    assert compile_calls.calls == []


def test_compile_route_accepts_registered_program(client, sandbox, compile_calls):
    (sandbox['root'] / 'st_files' / '123456.st').write_text('PROGRAM p END_PROGRAM\n')
    register_program(sandbox['root'] / 'openplc.db', '123456.st')

    resp = client.get('/compile-program', query_string={'file': '123456.st'})

    assert resp.status_code == 200
    assert compile_calls.calls == [['./scripts/compile_program.sh', '123456.st']]


# --------------------------------------------------------------------------
# /upload-program-action -> Programs table -> /compile-program chain
# --------------------------------------------------------------------------

def test_upload_action_rejects_traversal_prog_file(client, sandbox, compile_calls):
    before = programs_files(sandbox['root'] / 'openplc.db')

    resp = client.post('/upload-program-action', data={
        'prog_name': 'outside',
        'prog_descr': '',
        'prog_file': '../outside/evil.st',
        'epoch_time': '1700000000',
    })

    assert resp.status_code == 400
    assert programs_files(sandbox['root'] / 'openplc.db') == before

    # Even if the name had been registered, the compile route must still refuse it.
    resp = client.get('/compile-program', query_string={'file': '../outside/evil.st'})
    assert resp.status_code == 400
    assert compile_calls.calls == []


def test_upload_action_then_compile_with_registered_traversal_name(client, sandbox, compile_calls):
    # Simulates a Programs row that already carries a traversal name (tampered
    # DB or pre-fix upload): the compile route must not trust the table alone.
    register_program(sandbox['root'] / 'openplc.db', '../outside/evil.st')

    resp = client.get('/compile-program', query_string={'file': '../outside/evil.st'})

    assert resp.status_code == 400
    assert compile_calls.calls == []
    assert _active_program(sandbox) == 'blank_program.st\n'


# --------------------------------------------------------------------------
# openplc.runtime.compile_program (defence in depth below the route)
# --------------------------------------------------------------------------

def test_runtime_compile_program_rejects_outside_path(sandbox, compile_calls):
    import openplc

    rt = openplc.runtime()
    with pytest.raises(ValueError):
        rt.compile_program('../outside/evil.st')

    assert compile_calls.calls == []
    assert not (sandbox['root'] / 'core' / 'debug.cpp').exists()


def test_runtime_compile_program_accepts_plain_name(sandbox, compile_calls):
    import openplc

    rt = openplc.runtime()
    rt.compile_program('blank_program.st')

    assert compile_calls.calls == [['./scripts/compile_program.sh', 'blank_program.st']]


def test_is_safe_st_filename_helper(sandbox):
    import openplc

    for name in TRAVERSAL_NAMES + [None, 'a.st.dbg', 'a b.st', 'x.ST']:
        assert not openplc.is_safe_st_filename(name), name
    for name in ['blank_program.st', '123456.st', 'L4_WASH_01.st', 'my-prog.v2.st']:
        assert openplc.is_safe_st_filename(name), name


# --------------------------------------------------------------------------
# User picture upload: extension must come from the detected image type
# --------------------------------------------------------------------------

def _add_user(client, filename, data):
    return client.post('/add-user', data={
        'full_name': 'Sec Test',
        'user_name': 'sectest',
        'user_email': 'sec@test',
        'user_password': 'x',
        'file': (io.BytesIO(data), filename),
    }, content_type='multipart/form-data')


def test_picture_extension_derives_from_content_not_client_name(client, sandbox):
    # Client claims .png but the bytes are a GIF - stored name must say .gif.
    resp = _add_user(client, 'avatar.png', GIF_BYTES)
    assert resp.status_code == 302

    saved = os.listdir(sandbox['root'] / 'static')
    assert len(saved) == 1
    assert re.fullmatch(r'\d+\.gif', saved[0]), saved


def test_picture_upload_keeps_image_type_restriction(client, sandbox):
    resp = _add_user(client, 'avatar.txt', PNG_BYTES)
    assert resp.status_code == 400
    assert os.listdir(sandbox['root'] / 'static') == []

    resp = _add_user(client, 'shell.php', b'<?php echo 1; ?>')
    assert resp.status_code == 400
    assert os.listdir(sandbox['root'] / 'static') == []

    resp = _add_user(client, 'avatar.png', PNG_BYTES)
    assert resp.status_code == 302
    saved = os.listdir(sandbox['root'] / 'static')
    assert len(saved) == 1 and re.fullmatch(r'\d+\.png', saved[0]), saved
