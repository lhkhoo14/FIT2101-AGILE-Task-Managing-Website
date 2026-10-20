"""Account verification, password reset and email change (the newer auth routes)."""
import time

import pytest

import mailer
from api_helpers import PASSWORD, register

ALICE = "alice@monash.edu"


@pytest.fixture(autouse=True)
def offline_mail(monkeypatch):
    """Never send real email from these tests, whatever the developer's environment says."""
    monkeypatch.delenv("BREVO_API_KEY", raising=False)


@pytest.fixture
def links(monkeypatch):
    """Capture the (address, link) pairs the email-change flow would have emailed."""
    sent = []
    monkeypatch.setattr(mailer, "send_verification_email", lambda to, link: sent.append((to, link)) or True)
    return sent


def user_row(db, uid):
    return next(u for u in db.read()["users"] if u["user_id"] == uid)


def set_user(db, uid, **fields):
    state = db.read()
    next(u for u in state["users"] if u["user_id"] == uid).update(fields)
    db.write(state)


@pytest.mark.api
def test_unverified_account_must_verify_before_login(client, db):
    uid = register(client, "alice", verify=False)
    login = {"email": ALICE, "password": PASSWORD}
    assert client.post("/api/login", json=login).status_code == 403
    code = user_row(db, uid)["verify_code"]
    assert client.post("/api/verify-code", json={"email": ALICE, "code": "NOPE00"}).status_code == 400
    assert client.post("/api/verify-code", json={"email": "nobody@monash.edu", "code": "AAAAAA"}).status_code == 404
    ok = client.post("/api/verify-code", json={"email": ALICE, "code": code.lower()})
    assert ok.status_code == 200
    assert "verify_code" not in user_row(db, uid)
    assert client.post("/api/login", json=login).json()["user_id"] == uid
    assert client.post("/api/verify-code", json={"email": ALICE, "code": code}).status_code == 400


@pytest.mark.api
def test_reregistering_an_unverified_account_respects_the_cooldown(client, db):
    uid = register(client, "alice", verify=False)
    body = {"username": "alice2", "email": ALICE, "password": PASSWORD}
    assert client.post("/api/register", json=body).status_code == 429
    set_user(db, uid, last_email_sent_at=time.time() - 120)
    again = client.post("/api/register", json=body)
    assert again.status_code == 201 and again.json()["user_id"] == uid
    assert user_row(db, uid)["username"] == "alice2"


@pytest.mark.api
def test_resend_code_rules(client, db):
    uid = register(client, "alice", verify=False)
    register(client, "bob")
    url = "/api/resend-code"
    assert client.post(url, json={"email": "nobody@monash.edu"}).status_code == 404
    assert client.post(url, json={"email": "bob@monash.edu"}).status_code == 400   # already verified
    assert client.post(url, json={"email": ALICE}).status_code == 429               # cooldown
    set_user(db, uid, last_email_sent_at=time.time() - 120)
    ok = client.post(url, json={"email": ALICE})
    assert ok.status_code == 200 and ok.json()["email_sent"] is False
    assert user_row(db, uid)["verify_code"]


@pytest.mark.api
def test_check_email_availability(client):
    register(client, "alice")
    assert client.post("/api/register/check-email", json={"email": "ALICE@monash.edu"}).status_code == 400
    assert client.post("/api/register/check-email", json={"email": "free@monash.edu"}).status_code == 200


@pytest.mark.api
def test_unverified_accounts_expire_after_a_day(client, db):
    uid = register(client, "alice", verify=False)
    set_user(db, uid, created_at=time.time() - 90000)
    response = client.post("/api/login", json={"email": ALICE, "password": PASSWORD})
    assert response.status_code == 401   # purged, so the email is no longer registered


@pytest.mark.api
def test_forgot_and_reset_password_flow(client, db):
    uid = register(client, "alice")
    register(client, "bob", verify=False)
    assert client.post("/api/forgot-password", json={"email": "nobody@monash.edu"}).status_code == 404
    assert client.post("/api/forgot-password", json={"email": "bob@monash.edu"}).status_code == 400
    assert client.post("/api/forgot-password", json={"email": ALICE}).status_code == 200
    assert client.post("/api/forgot-password", json={"email": ALICE}).status_code == 429   # cooldown
    code = user_row(db, uid)["reset_code"]
    reset = {"email": ALICE, "code": code, "new_password": "BrandNew123"}
    assert client.post("/api/reset-password", json={**reset, "new_password": "short"}).status_code == 422
    assert client.post("/api/reset-password", json={**reset, "email": "nobody@monash.edu"}).status_code == 404
    assert client.post("/api/reset-password", json={**reset, "email": "bob@monash.edu"}).status_code == 400
    assert client.post("/api/reset-password", json=reset).status_code == 200
    assert client.post("/api/login", json={"email": ALICE, "password": "BrandNew123"}).status_code == 200
    assert client.post("/api/reset-password", json=reset).status_code == 400   # the code is single use


@pytest.mark.api
def test_reset_code_locks_after_too_many_wrong_guesses(client, db):
    uid = register(client, "alice")
    client.post("/api/forgot-password", json={"email": ALICE})
    bad = {"email": ALICE, "code": "ZZZZZZ", "new_password": "BrandNew123"}
    first = client.post("/api/reset-password", json=bad)
    assert first.status_code == 400 and "4 attempt(s) remaining" in first.json()["detail"]
    for _ in range(3):
        assert client.post("/api/reset-password", json=bad).status_code == 400
    assert client.post("/api/reset-password", json=bad).status_code == 429
    assert "reset_code" not in user_row(db, uid)


@pytest.mark.api
def test_expired_reset_code_is_refused(client, db):
    uid = register(client, "alice")
    client.post("/api/forgot-password", json={"email": ALICE})
    code = user_row(db, uid)["reset_code"]
    set_user(db, uid, reset_code_expires_at=time.time() - 1)
    response = client.post("/api/reset-password", json={"email": ALICE, "code": code, "new_password": "BrandNew123"})
    assert response.status_code == 400 and "expired" in response.json()["detail"]


@pytest.mark.api
def test_email_change_needs_the_password_and_a_valid_link(client, links):
    uid = register(client, "alice")
    register(client, "bob")
    url = f"/api/users/{uid}/email-change"
    new = {"new_email": "new@monash.edu"}
    assert client.post(url, json={**new, "current_password": "wrong"}).status_code == 401
    assert client.post(url, json={"new_email": "ALICE@monash.edu", "current_password": PASSWORD}).status_code == 400
    assert client.post(url, json={"new_email": "bob@monash.edu", "current_password": PASSWORD}).status_code == 409
    assert client.post("/api/users/99/email-change", json={**new, "current_password": PASSWORD}).status_code == 404
    ok = client.post(url, json={**new, "current_password": PASSWORD})
    assert ok.status_code == 200 and ok.json()["email_sent"] is True
    to, link = links[0]
    assert to == "new@monash.edu"
    token = link.split("verify_email=")[1]
    assert client.post("/api/users/email-verify", json={"token": "bogus"}).status_code == 400
    done = client.post("/api/users/email-verify", json={"token": token})
    assert done.status_code == 200 and done.json()["email"] == "new@monash.edu"
    assert client.post("/api/login", json={"email": "new@monash.edu", "password": PASSWORD}).status_code == 200
    assert client.post("/api/users/email-verify", json={"token": token}).status_code == 400   # single use


@pytest.mark.api
def test_email_link_expiry_and_address_collision(client, db, links):
    uid = register(client, "alice")
    url = f"/api/users/{uid}/email-change"
    body = {"new_email": "new@monash.edu", "current_password": PASSWORD}
    client.post(url, json=body)
    set_user(db, uid, pending_email_expires=time.time() - 1)
    expired = client.post("/api/users/email-verify", json={"token": links[0][1].split("verify_email=")[1]})
    assert expired.status_code == 400
    client.post(url, json=body)
    register(client, "bob", email="new@monash.edu")      # someone else takes the address first
    taken = client.post("/api/users/email-verify", json={"token": links[1][1].split("verify_email=")[1]})
    assert taken.status_code == 409