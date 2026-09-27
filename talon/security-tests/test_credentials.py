"""SECURITY-SWARM finding F1 — default and plaintext credentials.

CWE-256 / CWE-798 / CWE-1392. CVSS 3.1 AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H (9.8).

Before the fix the shipped ``Users`` table holds ``openplc``/``openplc`` in
cleartext and ``webserver.login()`` compares ``row[1] == password``. These
tests assert that (a) no cleartext password is stored, (b) the vendor default
credential cannot open a session as-is, (c) the verification helper accepts
the right password against a hash and rejects a wrong one while upgrading
legacy cleartext rows, and (d) every UI path that writes a password stores a
hash.
"""
import sqlite3

import pytest
from werkzeug.security import check_password_hash

try:
    import user_auth  # webserver/user_auth.py — absent on the pre-fix tree
except ModuleNotFoundError:
    user_auth = None

DEFAULT_USER = "openplc"
DEFAULT_PASS = "openplc"
HASH_PREFIXES = ("pbkdf2:", "scrypt:")


def _users(conn):
    return conn.execute("SELECT username, password FROM Users").fetchall()


def _looks_hashed(value):
    return isinstance(value, str) and value.startswith(HASH_PREFIXES) and "$" in value


def _login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def _seed_user(conn, username, password_value, name="Test User"):
    conn.execute(
        "INSERT INTO Users (name, username, email, password) VALUES (?, ?, ?, ?)",
        (name, username, f"{username}@example.invalid", password_value),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# (a) shipped database content
# --------------------------------------------------------------------------- #
def test_shipped_users_table_stores_no_cleartext_passwords(db_conn):
    rows = _users(db_conn)
    assert rows, "shipped openplc.db must ship at least one account"
    for username, stored in rows:
        assert stored != DEFAULT_PASS, f"{username}: vendor default password stored in cleartext"
        assert _looks_hashed(stored), f"{username}: password column is not a recognised hash: {stored!r}"


# --------------------------------------------------------------------------- #
# (b) the default credential does not authenticate as-is
# --------------------------------------------------------------------------- #
def test_default_credential_does_not_open_a_session(client):
    resp = _login(client, DEFAULT_USER, DEFAULT_PASS)
    assert not (resp.status_code == 302 and resp.headers["Location"].endswith("/dashboard")), (
        "openplc/openplc logged straight in to the dashboard"
    )
    # No authenticated session exists after posting the default credential.
    follow = client.get("/dashboard")
    assert follow.status_code == 302 and follow.headers["Location"].endswith("/login")


def test_default_credential_is_forced_through_password_rotation(client, db_copy):
    resp = _login(client, DEFAULT_USER, DEFAULT_PASS)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/change-password")

    page = client.get("/change-password")
    assert page.status_code == 200 and b"change-password" in page.data

    # Rotating back to the vendor default is refused.
    refused = client.post(
        "/change-password",
        data={"current_password": DEFAULT_PASS, "new_password": DEFAULT_PASS, "confirm_password": DEFAULT_PASS},
    )
    assert refused.status_code == 200 and b"default password" in refused.data

    new_pw = "Kingsport-L4-2026!"
    rotated = client.post(
        "/change-password",
        data={"current_password": DEFAULT_PASS, "new_password": new_pw, "confirm_password": new_pw},
    )
    assert rotated.status_code == 302 and rotated.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200

    conn = sqlite3.connect(str(db_copy))
    stored = conn.execute("SELECT password FROM Users WHERE username = ?", (DEFAULT_USER,)).fetchone()[0]
    conn.close()
    assert _looks_hashed(stored) and check_password_hash(stored, new_pw)

    client.get("/logout")
    assert b"Bad credentials" in _login(client, DEFAULT_USER, DEFAULT_PASS).data
    ok = _login(client, DEFAULT_USER, new_pw)
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/dashboard")


# --------------------------------------------------------------------------- #
# (c) verification helper
# --------------------------------------------------------------------------- #
def test_verify_helper_accepts_correct_and_rejects_wrong_password():
    assert user_auth is not None, "webserver/user_auth.py verification helper is missing"
    stored = user_auth.hash_password("correct horse battery staple")
    assert user_auth.is_password_hash(stored)
    assert stored != "correct horse battery staple"
    assert user_auth.verify_password(stored, "correct horse battery staple")
    assert not user_auth.verify_password(stored, "wrong")
    assert not user_auth.verify_password(stored, "")
    assert not user_auth.is_password_hash("openplc")


def test_verify_helper_upgrades_legacy_cleartext_row_on_login(db_conn):
    assert user_auth is not None, "webserver/user_auth.py verification helper is missing"
    _seed_user(db_conn, "legacy", "s3cret-legacy")

    assert not user_auth.authenticate(db_conn, "legacy", "wrong").ok
    assert not user_auth.authenticate(db_conn, "nobody", "s3cret-legacy").ok

    result = user_auth.authenticate(db_conn, "legacy", "s3cret-legacy")
    assert result.ok and result.session_allowed

    stored = db_conn.execute("SELECT password FROM Users WHERE username = 'legacy'").fetchone()[0]
    assert _looks_hashed(stored) and check_password_hash(stored, "s3cret-legacy")
    assert user_auth.authenticate(db_conn, "legacy", "s3cret-legacy").session_allowed
    assert not user_auth.authenticate(db_conn, "legacy", "wrong").ok


def test_verify_helper_flags_default_password_for_rotation(db_conn):
    assert user_auth is not None, "webserver/user_auth.py verification helper is missing"
    result = user_auth.authenticate(db_conn, DEFAULT_USER, DEFAULT_PASS)
    assert result.ok and result.rotation_required and not result.session_allowed
    with pytest.raises(ValueError):
        user_auth.set_password(db_conn, DEFAULT_USER, DEFAULT_PASS)
    with pytest.raises(ValueError):
        user_auth.set_password(db_conn, DEFAULT_USER, "")


# --------------------------------------------------------------------------- #
# (d) UI paths that write passwords store hashes
# --------------------------------------------------------------------------- #
def test_add_user_and_edit_user_store_hashed_passwords(client, db_copy):
    conn = sqlite3.connect(str(db_copy))
    _seed_user(conn, "admin", "Adm1n-pass-2026", name="Admin")
    conn.close()

    resp = _login(client, "admin", "Adm1n-pass-2026")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/dashboard")

    added = client.post(
        "/add-user",
        data={"full_name": "New Operator", "user_name": "operator", "user_email": "op@example.invalid",
              "user_password": "Op3rator-pass"},
    )
    assert added.status_code == 302 and added.headers["Location"].endswith("/users")

    conn = sqlite3.connect(str(db_copy))
    user_id, stored = conn.execute("SELECT user_id, password FROM Users WHERE username = 'operator'").fetchone()
    conn.close()
    assert stored != "Op3rator-pass", "add-user stored the password in cleartext"
    assert _looks_hashed(stored) and check_password_hash(stored, "Op3rator-pass")

    edited = client.post(
        "/edit-user",
        data={"user_id": str(user_id), "full_name": "New Operator", "user_name": "operator",
              "user_email": "op@example.invalid", "user_password": "R0tated-pass"},
    )
    assert edited.status_code == 302 and edited.headers["Location"].endswith("/users")

    conn = sqlite3.connect(str(db_copy))
    stored = conn.execute("SELECT password FROM Users WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()
    assert stored != "R0tated-pass", "edit-user stored the password in cleartext"
    assert _looks_hashed(stored) and check_password_hash(stored, "R0tated-pass")

    # The unchanged-password sentinel leaves the hash alone.
    client.post(
        "/edit-user",
        data={"user_id": str(user_id), "full_name": "Renamed", "user_name": "operator",
              "user_email": "op@example.invalid", "user_password": "mypasswordishere"},
    )
    conn = sqlite3.connect(str(db_copy))
    unchanged = conn.execute("SELECT password FROM Users WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()
    assert unchanged == stored

    client.get("/logout")
    ok = _login(client, "operator", "R0tated-pass")
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/dashboard")
