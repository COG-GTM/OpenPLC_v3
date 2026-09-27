"""F10 — missing authorization on REST API user management (CWE-862 / IDOR).

CVSS 3.1 AV:N/AC:L/PR:L/UI:N/S:U/C:N/I:H/A:L = 7.1 (High).

Any holder of a valid JWT can call DELETE /api/delete-user/<id> and
PUT /api/password-change/<id> against *another* account.  These tests fail on
the unpatched restapi.py (user B is deleted / re-passworded by user A) and pass
once the endpoints require the JWT identity to match the target user_id.
Self-service on the caller's own account must keep working unchanged.
"""
import pytest

USER_A = {"username": "alice", "password": "alice-pw-1"}
USER_B = {"username": "bob", "password": "bob-pw-1"}


def _login(client, username, password):
    rv = client.post("/api/login", json={"username": username, "password": password})
    return rv


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two_users(fresh_db):
    """Users A and B exist; returns (client, id_a, id_b, token_a)."""
    client = fresh_db.app_restapi.test_client()
    # bootstrap: first user is created without a JWT
    rv = client.post("/api/create-user", json=USER_A)
    assert rv.status_code == 201, rv.get_json()
    id_a = rv.get_json()["id"]

    rv = _login(client, **USER_A)
    assert rv.status_code == 200, rv.get_json()
    token_a = rv.get_json()["access_token"]

    rv = client.post("/api/create-user", json=USER_B, headers=_auth(token_a))
    assert rv.status_code == 201, rv.get_json()
    id_b = rv.get_json()["id"]
    assert id_a != id_b
    return client, id_a, id_b, token_a


def test_delete_other_user_is_forbidden(two_users):
    client, id_a, id_b, token_a = two_users

    rv = client.delete(f"/api/delete-user/{id_b}", headers=_auth(token_a))
    assert rv.status_code == 403, (rv.status_code, rv.get_json())

    # B is intact and can still log in.
    assert _login(client, **USER_B).status_code == 200
    # A's token was not revoked by the rejected call.
    rv = client.get(f"/api/get-user-info/{id_a}", headers=_auth(token_a))
    assert rv.status_code == 200


def test_change_other_users_password_is_forbidden(two_users):
    client, id_a, id_b, token_a = two_users

    rv = client.put(
        f"/api/password-change/{id_b}",
        json={"old_password": USER_B["password"], "new_password": "owned"},
        headers=_auth(token_a),
    )
    assert rv.status_code == 403, (rv.status_code, rv.get_json())

    # B's password is unchanged.
    assert _login(client, **USER_B).status_code == 200
    assert _login(client, USER_B["username"], "owned").status_code == 401


def test_read_other_users_info_is_forbidden(two_users):
    client, id_a, id_b, token_a = two_users

    rv = client.get(f"/api/get-user-info/{id_b}", headers=_auth(token_a))
    assert rv.status_code == 403, (rv.status_code, rv.get_json())


def test_self_service_still_works(two_users):
    client, id_a, id_b, token_a = two_users

    # A can read A.
    rv = client.get(f"/api/get-user-info/{id_a}", headers=_auth(token_a))
    assert rv.status_code == 200
    assert rv.get_json()["username"] == USER_A["username"]

    # A can change A's password (old password still verified).
    rv = client.put(
        f"/api/password-change/{id_a}",
        json={"old_password": "wrong", "new_password": "alice-pw-2"},
        headers=_auth(token_a),
    )
    assert rv.status_code == 403
    rv = client.put(
        f"/api/password-change/{id_a}",
        json={"old_password": USER_A["password"], "new_password": "alice-pw-2"},
        headers=_auth(token_a),
    )
    assert rv.status_code == 200, rv.get_json()
    assert _login(client, USER_A["username"], "alice-pw-2").status_code == 200

    # A can delete A, and the token used for it is revoked afterwards.
    rv = client.delete(f"/api/delete-user/{id_a}", headers=_auth(token_a))
    assert rv.status_code == 200, rv.get_json()
    assert _login(client, USER_A["username"], "alice-pw-2").status_code == 401
    rv = client.get(f"/api/get-user-info/{id_a}", headers=_auth(token_a))
    assert rv.status_code == 401  # revoked

    # B untouched.
    assert _login(client, **USER_B).status_code == 200
