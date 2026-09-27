"""Credential storage and verification for the legacy web UI ``Users`` table.

Passwords are stored as Werkzeug PBKDF2 hashes using the same derivation
method as the REST API ``User`` model in ``restapi.py``. Rows that still hold
a legacy cleartext password are accepted once and rewritten as a hash on
successful login. The vendor default credential can never open a session:
verifying against it reports ``rotation_required`` and the caller must make
the operator choose a new password first.
"""
import hmac
from dataclasses import dataclass
from sqlite3 import Connection

from werkzeug.security import check_password_hash, generate_password_hash

HASH_METHOD = "pbkdf2:sha256:600000"
HASH_PREFIXES = ("pbkdf2:", "scrypt:")

DEFAULT_USERNAME = "openplc"
DEFAULT_PASSWORD = "openplc"

PASSWORD_UNCHANGED_SENTINEL = "mypasswordishere"


@dataclass
class AuthResult:
    ok: bool = False
    rotation_required: bool = False
    username: str = ""
    name: str = ""
    pict_file: str = ""

    @property
    def session_allowed(self):
        return self.ok and not self.rotation_required


def hash_password(password):
    return generate_password_hash(password, method=HASH_METHOD)


def is_password_hash(stored):
    if not isinstance(stored, str) or "$" not in stored:
        return False
    return stored.startswith(HASH_PREFIXES)


def verify_password(stored, candidate):
    if stored is None or candidate is None:
        return False
    if is_password_hash(stored):
        return check_password_hash(stored, candidate)
    return hmac.compare_digest(str(stored).encode("utf-8"), str(candidate).encode("utf-8"))


def is_default_password(password):
    return hmac.compare_digest(str(password).encode("utf-8"), DEFAULT_PASSWORD.encode("utf-8"))


def authenticate(conn: Connection, username, password):
    """Verify ``username``/``password`` against the ``Users`` table.

    Upgrades a matching legacy cleartext row to a hash. Never grants a session
    for the vendor default password: ``rotation_required`` is set instead.
    """
    result = AuthResult(username=str(username))
    cur = conn.cursor()
    cur.execute("SELECT username, password, name, pict_file FROM Users WHERE username = ?", (username,))
    row = cur.fetchone()
    if row is None:
        cur.close()
        return result

    if not verify_password(row[1], password):
        cur.close()
        return result

    if not is_password_hash(row[1]):
        cur.execute("UPDATE Users SET password = ? WHERE username = ?", (hash_password(password), username))
        conn.commit()
    cur.close()

    result.ok = True
    result.rotation_required = is_default_password(password)
    result.name = str(row[2])
    result.pict_file = str(row[3])
    return result


def set_password(conn: Connection, username, new_password):
    """Store a new hashed password. Refuses empty and vendor-default values."""
    if not new_password:
        raise ValueError("Password cannot be blank")
    if is_default_password(new_password):
        raise ValueError("The default password cannot be used")
    cur = conn.cursor()
    cur.execute("UPDATE Users SET password = ? WHERE username = ?", (hash_password(new_password), username))
    conn.commit()
    cur.close()
