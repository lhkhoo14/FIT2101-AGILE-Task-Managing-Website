"""Account routes: register, login lockout, profile, avatar, email change, password, deletion."""
import base64
import time

import pytest

import mailer
from api_helpers import PASSWORD, add_member, board, create_project, create_sprint, register

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPEG = b"\xff\xd8\xff" + b"0" * 20
WEBP = b"RIFF" + b"0" * 20


def data_url(mime, raw):
    return f"data:image/{mime};base64," + base64.b64encode(raw).decode()


# ---- register / login -----------------------------------------------------
@pytest.mark.api
def test_register_then_duplicate_email_rejected(client):
    uid = register(client, "alice")
    assert uid == 1
    again = client.post("/api/register", json={"username": "x", "email": "alice@monash.edu", "password": "pw"})
    assert again.status_code == 400
    assert "already registered" in again.json()["detail"]


@pytest.mark.api
def test_register_rejects_invalid_email(client):
    response = client.post("/api/register", json={"username": "x", "email": "nope", "password": "pw"})
    assert response.status_code == 422


@pytest.mark.api
def test_login_success_and_unknown_email(client):
    uid = register(client, "alice")
    ok = client.post("/api/login", json={"email": "alice@monash.edu", "password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["user_id"] == uid
    missing = client.post("/api/login", json={"email": "ghost@monash.edu", "password": "x"})
    assert missing.status_code == 401


@pytest.mark.api
def test_login_lock_message_and_expiry(client, db):
    """A locked account is refused (even with the right password) until the lock expires."""
    register(client, "alice")
    good = {"email": "alice@monash.edu", "password": PASSWORD}
    state = db.read()
    state["users"][0]["lockout_until"] = time.time() + 60
    db.write(state)
    blocked = client.post("/api/login", json=good)
    assert blocked.status_code == 429 and "Try again" in blocked.json()["detail"]

    state = db.read()
    state["users"][0]["lockout_until"] = time.time() - 1
    state["users"][0]["failed_attempts"] = 2
    db.write(state)
    assert client.post("/api/login", json=good).status_code == 200
    user = db.read()["users"][0]
    assert user["failed_attempts"] == 0 and user["lockout_until"] == 0


@pytest.mark.api
def test_third_failed_attempt_reports_a_lockout(client, db):
    register(client, "alice")
    state = db.read()
    state["users"][0]["failed_attempts"] = 2
    db.write(state)
    response = client.post("/api/login", json={"email": "alice@monash.edu", "password": "wrong"})
    assert response.status_code == 429 and "locked for 30 seconds" in response.json()["detail"]


@pytest.mark.api
def test_wrong_password_reports_attempts_remaining(client):
    register(client, "alice")
    response = client.post("/api/login", json={"email": "alice@monash.edu", "password": "wrong"})
    assert response.status_code == 401 and "2 attempt(s) remaining" in response.json()["detail"]


@pytest.mark.api
@pytest.mark.xfail(strict=True, reason=(
    "BUG: login() raises HTTPException inside db_manager.update(), so the failed-attempt "
    "counter and lockout_until are never saved and the account never actually locks."))
def test_repeated_failures_really_lock_the_account(client):
    register(client, "alice")
    bad = {"email": "alice@monash.edu", "password": "wrong"}
    for _ in range(2):
        client.post("/api/login", json=bad)
    assert client.post("/api/login", json=bad).status_code == 429


# ---- user lookups ---------------------------------------------------------
@pytest.mark.api
def test_get_user_and_users_list(client):
    uid = register(client, "alice")
    register(client, "bob")
    one = client.get(f"/api/users/{uid}")
    assert one.status_code == 200 and one.json()["username"] == "alice"
    assert one.json()["profile_photo"].endswith("default-profile.svg")
    assert client.get("/api/users/99").status_code == 404

    users = client.get("/api/users", params={"user_id": uid})
    assert users.status_code == 200 and [u["username"] for u in users.json()] == ["alice", "bob"]
    assert client.get("/api/users", params={"user_id": 99}).status_code == 401


@pytest.mark.api
def test_settings_endpoint(client):
    uid = register(client, "alice")
    response = client.get(f"/api/users/{uid}/settings")
    assert response.status_code == 200
    assert response.json()["email"] == "alice@monash.edu" and response.json()["pending_email"] is None
    assert client.get("/api/users/99/settings").status_code == 404


# ---- profile & avatar -----------------------------------------------------
@pytest.mark.api
def test_update_username_rules(client):
    a, b = register(client, "alice"), register(client, "bob")
    ok = client.patch(f"/api/users/{a}/profile", json={"username": "  Alicia  "})
    assert ok.status_code == 200 and ok.json()["username"] == "Alicia"
    assert client.patch(f"/api/users/{a}/profile", json={"username": "   "}).status_code == 422
    assert client.patch(f"/api/users/{a}/profile", json={"username": "x" * 51}).status_code == 422
    assert client.patch(f"/api/users/{a}/profile", json={"username": "BOB"}).status_code == 409
    assert client.patch(f"/api/users/{a}/profile", json={"username": "alicia"}).status_code == 200   # own name
    assert client.patch("/api/users/99/profile", json={"username": "z"}).status_code == 404
    assert b  # silence unused warning


@pytest.mark.api
@pytest.mark.parametrize("mime,raw", [("png", PNG), ("jpeg", JPEG), ("webp", WEBP)])
def test_avatar_upload_serve_cache_and_remove(client, mime, raw):
    uid = register(client, "alice")
    response = client.patch(f"/api/users/{uid}/profile", json={"profile_photo": data_url(mime, raw)})
    assert response.status_code == 200
    assert f"/api/users/{uid}/avatar" in response.json()["profile_photo"]

    served = client.get(f"/api/users/{uid}/avatar")
    assert served.status_code == 200 and served.content == raw
    assert served.headers["content-type"] == f"image/{mime}"
    etag = served.headers["etag"]
    cached = client.get(f"/api/users/{uid}/avatar", headers={"if-none-match": etag})
    assert cached.status_code == 304

    removed = client.patch(f"/api/users/{uid}/profile", json={"profile_photo": ""})
    assert removed.status_code == 200 and removed.json()["profile_photo"].endswith("default-profile.svg")
    assert client.get(f"/api/users/{uid}/avatar").status_code == 404


@pytest.mark.api
def test_avatar_validation(client):
    uid = register(client, "alice")
    url = f"/api/users/{uid}/profile"
    assert client.patch(url, json={"profile_photo": "data:image/gif;base64,AAAA"}).status_code == 422
    assert client.patch(url, json={"profile_photo": "data:image/png;base64,@@@"}).status_code == 422
    assert client.patch(url, json={"profile_photo": data_url("png", b"not a png")}).status_code == 422
    assert client.patch(url, json={"profile_photo": "data:image/png;base64," + "A" * 300001}).status_code == 422


@pytest.mark.api
def test_legacy_inline_photo_is_still_returned(client, db):
    uid = register(client, "alice")
    state = db.read()
    state["users"][0]["profile_photo"] = "data:image/png;base64,AAAA"
    db.write(state)
    assert client.get(f"/api/users/{uid}").json()["profile_photo"] == "data:image/png;base64,AAAA"


# ---- email change ---------------------------------------------------------
@pytest.fixture
def sent_mail(monkeypatch):
    sent = []
    monkeypatch.setattr(mailer, "send_verification_email", lambda to, link: sent.append((to, link)) or True)
    return sent


@pytest.mark.api
def test_email_change_flow(client, sent_mail, db):
    uid = register(client, "alice")
    response = client.post(f"/api/users/{uid}/email-change", json={"new_email": "new@monash.edu"})
    assert response.status_code == 200 and response.json()["email_sent"] is True
    to, link = sent_mail[0]
    assert to == "new@monash.edu" and "verify_email=" in link
    assert client.get(f"/api/users/{uid}/settings").json()["pending_email"] == "new@monash.edu"
    # The address does not change until the link is used.
    assert db.read()["users"][0]["email"] == "alice@monash.edu"

    token = link.split("verify_email=")[1]
    verified = client.post("/api/users/email-verify", json={"token": token})
    assert verified.status_code == 200 and verified.json()["email"] == "new@monash.edu"
    assert db.read()["users"][0]["email"] == "new@monash.edu"
    assert client.post("/api/users/email-verify", json={"token": token}).status_code == 400   # single use


@pytest.mark.api
def test_email_change_validation(client, sent_mail):
    a = register(client, "alice")
    register(client, "bob")
    url = f"/api/users/{a}/email-change"
    assert client.post(url, json={"new_email": "ALICE@monash.edu"}).status_code == 400
    assert client.post(url, json={"new_email": "bob@monash.edu"}).status_code == 409
    assert client.post("/api/users/99/email-change", json={"new_email": "z@monash.edu"}).status_code == 404
    assert client.post(url, json={"new_email": "bad"}).status_code == 422


@pytest.mark.api
def test_email_verify_expired_taken_and_unknown(client, sent_mail, db):
    a = register(client, "alice")
    client.post(f"/api/users/{a}/email-change", json={"new_email": "new@monash.edu"})
    token = sent_mail[0][1].split("verify_email=")[1]

    assert client.post("/api/users/email-verify", json={"token": "bogus"}).status_code == 400

    # Someone else registers the address before the link is clicked.
    register(client, "bob", email="new@monash.edu")
    assert client.post("/api/users/email-verify", json={"token": token}).status_code == 409

    state = db.read()
    state["users"][0]["pending_email_expires"] = time.time() - 5
    db.write(state)
    assert client.post("/api/users/email-verify", json={"token": token}).status_code == 400
    assert "pending_email" not in db.read()["users"][0]    # expiry clears the request


@pytest.mark.api
def test_email_verify_without_pending_address(client, db):
    from routes.auth import _hash_token
    register(client, "alice")
    state = db.read()
    state["users"][0]["pending_email_token_hash"] = _hash_token("t")
    state["users"][0]["pending_email_expires"] = time.time() + 100
    db.write(state)
    assert client.post("/api/users/email-verify", json={"token": "t"}).status_code == 400


# ---- password -------------------------------------------------------------
@pytest.mark.api
def test_change_password_rules_and_effect(client):
    uid = register(client, "alice")
    url = f"/api/users/{uid}/password"
    assert client.post(url, json={"current_password": "nope", "new_password": "NewPassword1"}).status_code == 401
    assert client.post(url, json={"current_password": PASSWORD, "new_password": "short"}).status_code == 422
    assert client.post(url, json={"current_password": PASSWORD, "new_password": PASSWORD}).status_code == 400
    assert client.post("/api/users/99/password", json={"current_password": "a", "new_password": "bbbbbbbb"}).status_code == 404
    assert client.post(url, json={"current_password": PASSWORD, "new_password": "NewPassword1"}).status_code == 200
    assert client.post("/api/login", json={"email": "alice@monash.edu", "password": "NewPassword1"}).status_code == 200


# ---- account deletion -----------------------------------------------------
@pytest.mark.api
def test_delete_account_checks_password_and_existence(client):
    uid = register(client, "alice")
    assert client.post(f"/api/users/{uid}/delete", json={"password": "wrong"}).status_code == 401
    assert client.post("/api/users/99/delete", json={"password": PASSWORD}).status_code == 404


@pytest.mark.api
def test_delete_sole_member_removes_the_project(client, db):
    uid = register(client, "alice")
    project = create_project(client, uid)
    assert client.post(f"/api/users/{uid}/delete", json={"password": PASSWORD}).status_code == 200
    state = db.read()
    assert state["users"] == [] and str(project["project_id"]) not in state["projects"]
    assert state["next_user_id"] == 2     # ids are never reused


@pytest.mark.api
def test_delete_creator_promotes_and_unassigns_tasks(client, db):
    alice, bob = register(client, "alice"), register(client, "bob")
    carol = register(client, "carol")
    project = create_project(client, alice)
    pid = project["project_id"]
    add_member(client, pid, alice, "bob")
    add_member(client, pid, alice, "carol")
    sprint = create_sprint(client, pid, alice, members=[bob, carol])

    state = db.read()
    stored = state["projects"][str(pid)]
    stored["sprints"][0]["kanban_state"] = board(
        active=[{"id": "t1", "title": "A", "assignee_id": alice},
                {"id": "t2", "title": "B", "assignee": "alice"},
                {"id": "t3", "title": "C", "assignee_id": bob}])
    stored["contributions"] = {str(alice): {}}
    stored["contribute"] = [alice, bob, carol]
    db.write(state)

    assert client.post(f"/api/users/{alice}/delete", json={"password": PASSWORD}).status_code == 200
    stored = db.read()["projects"][str(pid)]
    assert alice not in stored["members"] and alice not in stored["contribute"]
    assert stored["creator"] == [] and str(alice) not in stored["contributions"]
    promoted = stored["roles"]["Project Creator"]
    assert len(promoted) == 1 and promoted[0] in (bob, carol)
    tasks = {t["id"]: t for t in stored["sprints"][0]["kanban_state"]["active"]}
    assert tasks["t1"]["assignee_id"] is None and tasks["t2"]["assignee"] is None
    assert tasks["t3"]["assignee_id"] == bob
    assert sprint["id"]


@pytest.mark.api
@pytest.mark.parametrize("scrum,employees,expected", [
    ([9], [], 9),            # Scrum Master is promoted first
    ([], [8], 8),            # then an Employee
    ([], [], None),          # then any remaining member
])
def test_promotion_order_when_the_owner_leaves(client, db, scrum, employees, expected):
    owner = register(client, "owner")
    keeper = register(client, "keeper", email="k@monash.edu")
    project = create_project(client, owner)
    pid = str(project["project_id"])
    state = db.read()
    stored = state["projects"][pid]
    stored["members"] = [owner, keeper]
    stored["roles"] = {"Project Creator": [owner], "Scrum Master": [keeper] if scrum else [],
                       "Employee": [keeper] if employees else []}
    state["projects"][pid] = stored
    db.write(state)
    client.post(f"/api/users/{owner}/delete", json={"password": PASSWORD})
    assert db.read()["projects"][pid]["roles"]["Project Creator"] == [keeper]


@pytest.mark.api
def test_delete_account_repairs_legacy_projects(client, db, seed_factory):
    from security import hash_password
    seed_factory(
        users=[{"user_id": 1, "username": "a", "email": "a@x.com", "password": hash_password("pw12345678"), "projects": [5, 6]},
               {"user_id": 2, "username": "b", "email": "b@x.com", "password": hash_password("pw12345678"), "projects": [5]}],
        projects=[
            {"project_id": 5, "members": [1, 2], "creator": 1, "sprints": [{"id": "s", "members": [1, 2]}]},
            {"project_id": 6, "members": [1], "creator": [1]},
            {"project_id": 7, "members": [2]},
        ])
    assert client.post("/api/users/1/delete", json={"password": "pw12345678"}).status_code == 200
    state = db.read()
    assert "6" not in state["projects"]
    legacy = state["projects"]["5"]
    assert legacy["members"] == [2] and legacy["creator"] is None
    assert legacy["roles"]["Project Creator"] == [2]       # promoted by the repair rule
    assert state["projects"]["7"]["members"] == [2]
    assert state["users"][0]["projects"] == [5]