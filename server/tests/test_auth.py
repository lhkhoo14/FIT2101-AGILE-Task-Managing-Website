"""Regression checks for the authentication rules that the merge reworked.

Each section pins one behaviour that was wrong (or unsafe) before the fixes in
routes/auth.py, and would go back to being wrong silently if the rule regressed:

  1. a failed password is counted, and three of them lock the account
  2. accounts created before is_verified existed can still log in
  3. ...and are not treated as new registrations (that used to be a 500)
  4. email addresses are matched regardless of case
  5. the verification mail is sent after the code is stored, not inside the write
  6. a rejected profile update leaves the stored picture alone
  7. registering again restarts the 24-hour window before an unverified account
     is purged
  8. a password reset clears a lockout, and a reset code cannot be guessed forever

Drives the real FastAPI app in-process against a temporary JSON database, so the
tracked server/data/server_database.json is never opened. Run it from the
repository root with:

    .venv\\Scripts\\python.exe server\\tests\\test_auth.py

Every check is printed and the process exits non-zero if any failed. It is a
plain script rather than a pytest module because the repository has no test
runner configured.
"""
import base64
import json
import os
import re
import sys
import tempfile
import time

os.environ.pop("DATABASE_URL", None)
# Keep the mailer offline: a real key in the environment would otherwise make
# these checks send genuine email.
os.environ.pop("BREVO_API_KEY", None)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import database_manager  # noqa: E402
import mailer  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from security import hash_password  # noqa: E402
from main import app  # noqa: E402

# One pixel PNG, and a second image that differs from it so the two uploads
# cannot be confused for each other.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PNG_ALT = PNG_1PX + b"\x00\x00\x00\x00"
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()
PNG_ALT_URL = "data:image/png;base64," + base64.b64encode(PNG_ALT).decode()

DB_PATH = os.path.join(tempfile.mkdtemp(prefix="auth_"), "auth_db.json")
database_manager.db_manager.db_path = DB_PATH

VERIFIED = {
    "user_id": 1, "username": "Alice", "email": "alice@example.com",
    "password": hash_password("Password123"), "is_verified": True,
    "created_at": 1767225600, "projects": [],
}
LOCKOUT_SUBJECT = {
    "user_id": 2, "username": "Bob", "email": "bob@example.com",
    "password": hash_password("Password123"), "is_verified": True,
    "created_at": 1767225600, "projects": [],
}
# Exactly what the tracked database contains for accounts made before email
# verification existed: no is_verified, no created_at.
LEGACY = {
    "user_id": 3, "username": "Legacy", "email": "legacy@example.com",
    "password": hash_password("Password123"), "projects": [],
    "failed_attempts": 0, "lockout_until": 0,
}
RESETTER = {
    "user_id": 4, "username": "Carol", "email": "carol@example.com",
    "password": hash_password("Password123"), "is_verified": True,
    "created_at": 1767225600, "projects": [],
}

SEED = {
    "next_user_id": 5, "next_project_id": 1, "next_backlog_id": 1, "next_sprint_id": 1,
    "users": [VERIFIED, LOCKOUT_SUBJECT, LEGACY, RESETTER],
    "projects": {},
}


def write_seed() -> None:
    with open(DB_PATH, "w", encoding="utf-8") as handle:
        json.dump(SEED, handle, indent=4)


def read_db() -> dict:
    with open(DB_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def patch_user(email: str, **fields) -> None:
    """Change fields of one seeded account directly, as time or an admin would."""
    data = read_db()
    for user in data["users"]:
        if user["email"] == email:
            user.update(fields)
    with open(DB_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4)


def get_user(email: str) -> dict | None:
    return next((u for u in read_db()["users"] if u["email"] == email), None)


write_seed()
client = TestClient(app, raise_server_exceptions=False)

results = []
failures = []


def check(label, condition, detail: object = ""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + ("" if condition else f"  <- {detail}"))
    if not condition:
        failures.append(label)


def login(email: str, password: str = "Password123"):
    return client.post("/api/login", json={"email": email, "password": password})


def register(email: str, username: str = "Newcomer", password: str = "Password123"):
    return client.post(
        "/api/register",
        json={"email": email, "username": username, "password": password},
    )


def detail(response) -> str:
    try:
        return str(response.json().get("detail", ""))
    except Exception:
        return response.text


print("\n-- 1. a failed password is counted, and the lockout sticks --")
first = login("bob@example.com", "WrongPassword1")
check("first wrong password is rejected", first.status_code == 401, first.status_code)
check("first wrong password says two attempts remain",
      "2 attempt(s) remaining" in detail(first), detail(first))
check("the attempt is stored", (get_user("bob@example.com") or {}).get("failed_attempts") == 1,
      (get_user("bob@example.com") or {}).get("failed_attempts"))

second = login("bob@example.com", "WrongPassword2")
check("second wrong password says one attempt remains",
      second.status_code == 401 and "1 attempt(s) remaining" in detail(second), detail(second))

third = login("bob@example.com", "WrongPassword3")
check("third wrong password locks the account", third.status_code == 429, third.status_code)
check("the lockout message carries the duration",
      "locked for 30 seconds" in detail(third), detail(third))

locked = get_user("bob@example.com") or {}
check("three attempts are stored", locked.get("failed_attempts") == 3, locked.get("failed_attempts"))
check("the lockout deadline is stored", (locked.get("lockout_until") or 0) > time.time(),
      locked.get("lockout_until"))

check("the correct password is refused while locked", login("bob@example.com").status_code == 429)

patch_user("bob@example.com", lockout_until=time.time() - 1)
after = login("bob@example.com")
check("login works once the lockout expires", after.status_code == 200, after.status_code)
recovered = get_user("bob@example.com") or {}
check("a successful login clears the counters",
      not recovered.get("failed_attempts") and not recovered.get("lockout_until"), recovered)

print("\n-- 2/3. accounts from before email verification --")
legacy_login = login("legacy@example.com")
check("a legacy account can log in", legacy_login.status_code == 200,
      f"{legacy_login.status_code} {detail(legacy_login)}")
check("logging in does not invent an is_verified flag",
      "is_verified" not in (get_user("legacy@example.com") or {}))

legacy_register = register("legacy@example.com", "Legacy")
check("registering a legacy address is a clean 400, not a 500",
      legacy_register.status_code == 400,
      f"{legacy_register.status_code} {legacy_register.text[:120]}")
check("the 400 explains the address is taken",
      "already registered" in detail(legacy_register), detail(legacy_register))

check("check-email reports a legacy address as taken",
      client.post("/api/register/check-email",
                  json={"email": "legacy@example.com"}).status_code == 400)
check("a legacy account can reset its password",
      client.post("/api/forgot-password",
                  json={"email": "legacy@example.com"}).status_code == 200)
check("a legacy account is not asked to verify a code it never had",
      client.post("/api/verify-code",
                  json={"email": "legacy@example.com", "code": "ABC123"}).status_code == 400)

print("\n-- 4. email addresses match regardless of case --")
check("login accepts the address in another case", login("ALICE@EXAMPLE.COM").status_code == 200)
check("check-email rejects the address in another case",
      client.post("/api/register/check-email",
                  json={"email": "Alice@Example.Com"}).status_code == 400)
check("registering the address in another case does not create a second account",
      register("Alice@Example.COM").status_code == 400)
check("forgot-password accepts the address in another case",
      client.post("/api/forgot-password",
                  json={"email": "Alice@Example.com"}).status_code == 200)

mixed = register("Mixed.Case@Example.COM", "Mixed")
check("a new account registers with a mixed-case address", mixed.status_code == 201,
      mixed.status_code)
mixed_user = get_user("mixed.case@example.com")
check("the address is stored lower-cased", mixed_user is not None,
      [u["email"] for u in read_db()["users"]])
check("the new account still has to verify", login("MIXED.CASE@example.com").status_code == 403)
verified = client.post(
    "/api/verify-code",
    json={"email": "mixed.case@EXAMPLE.com", "code": (mixed_user or {}).get("verify_code", "")},
)
check("the code verifies whatever case it is typed in", verified.status_code == 200, detail(verified))
check("the account logs in afterwards", login("MiXeD.CaSe@Example.com").status_code == 200)

print("\n-- passwords are stored and compared exactly as typed --")
# The browser used to trim the password field on the login page while signup
# stored it verbatim, so surrounding spaces could never be matched. The server
# side of that contract is checked here; test_deletions.py checks that no client
# module trims a password field again.
spaced = register("Spaced@Example.com", "Spaced", " Password123 ")
check("a password with surrounding spaces registers", spaced.status_code == 201,
      spaced.status_code)
spaced_user = get_user("spaced@example.com") or {}
client.post("/api/verify-code",
            json={"email": "spaced@example.com", "code": spaced_user.get("verify_code", "")})
check("the trimmed form of that password does not match",
      login("spaced@example.com", "Password123").status_code == 401)
check("the password exactly as typed does match",
      login("spaced@example.com", " Password123 ").status_code == 200)

print("\n-- 5. mail is sent after the code is stored --")
sent_at = {}


def record_send(to_email, code):
    """Stand-in for Brevo: look the account up only once the write is done."""
    stored = get_user(to_email.strip().lower())
    sent_at[to_email] = {
        "account_visible": stored is not None,
        # A verification code is kept in verify_code, a reset code in reset_code.
        "code_matches": bool(stored) and code in (stored.get("verify_code"),
                                                  stored.get("reset_code")),
    }
    return False


real_send_code = mailer.send_verification_code
real_send_reset = mailer.send_password_reset_code
mailer.send_verification_code = record_send
mailer.send_password_reset_code = record_send

try:
    ordered = register("Ordered@Example.com", "Ordered")
    check("register succeeds", ordered.status_code == 201, ordered.status_code)
    seen = sent_at.get("ordered@example.com", {})
    check("the account exists in the database when the mail goes out",
          seen.get("account_visible") is True, seen)
    check("the code in the mail is the one that was stored",
          seen.get("code_matches") is True, seen)
    body = ordered.json()
    check("the response says the mail did not go out", body.get("email_sent") is False, body)
    check("the response never carries the code",
          "_code" not in body and "verify_code" not in body, body)

    reset_request = client.post("/api/forgot-password", json={"email": "carol@example.com"})
    check("forgot-password succeeds", reset_request.status_code == 200, reset_request.status_code)
    seen_reset = sent_at.get("carol@example.com", {})
    check("the reset code is stored before the mail goes out",
          seen_reset.get("account_visible") is True and seen_reset.get("code_matches") is True,
          seen_reset)
    check("forgot-password reports the mail did not go out",
          reset_request.json().get("email_sent") is False, reset_request.json())
finally:
    mailer.send_verification_code = real_send_code
    mailer.send_password_reset_code = real_send_reset

print("\n-- 6. a rejected profile update leaves the picture alone --")
upload = client.patch("/api/users/1/profile",
                      json={"username": "Alice", "profile_photo": PNG_URL})
check("an avatar upload is accepted", upload.status_code == 200, upload.text[:120])
first_url = str(upload.json().get("profile_photo", ""))
version = re.search(r"\?v=(\d+)", first_url)
check("the picture URL carries a cache key", version is not None, first_url)
check("the cache key has sub-second resolution",
      version is not None and int(version.group(1)) > 1_000_000_000_000,
      version.group(1) if version else None)
check("the bytes are stored",
      database_manager.db_manager.get_user_avatar(1) == ("image/png", PNG_1PX),
      database_manager.db_manager.get_user_avatar(1))

rejected = client.patch("/api/users/1/profile",
                        json={"username": "Bob", "profile_photo": PNG_ALT_URL})
check("a taken display name is rejected", rejected.status_code == 409, rejected.status_code)
stored_avatar = database_manager.db_manager.get_user_avatar(1)
check("the rejected upload did not replace the stored bytes",
      stored_avatar == ("image/png", PNG_1PX),
      "missing" if stored_avatar is None else len(stored_avatar[1]))

rejected_removal = client.patch("/api/users/1/profile",
                                json={"username": "Bob", "profile_photo": ""})
check("removing the picture is rejected with the same bad name",
      rejected_removal.status_code == 409, rejected_removal.status_code)
check("the picture survives a rejected removal",
      database_manager.db_manager.get_user_avatar(1) == ("image/png", PNG_1PX))

second_upload = client.patch("/api/users/1/profile",
                             json={"username": "Alice", "profile_photo": PNG_ALT_URL})
check("a second upload is accepted", second_upload.status_code == 200, second_upload.text[:120])
second_url = str(second_upload.json().get("profile_photo", ""))
check("the second upload gets a different cache key", second_url != first_url,
      f"{first_url} vs {second_url}")

print("\n-- 7. registering again restarts the purge window --")
register("pending@example.com", "Pending")
# 23h59m50s old: the next request would purge it as abandoned.
patch_user("pending@example.com", created_at=time.time() - 86390, last_email_sent_at=0)
again = register("pending@example.com", "Pending")
check("registering an unverified address again succeeds", again.status_code == 201,
      again.status_code)
fresh = get_user("pending@example.com") or {}
check("the registration time is refreshed",
      time.time() - (fresh.get("created_at") or 0) < 30, fresh.get("created_at"))
still_there = login("pending@example.com")
check("the account survives the next request", still_there.status_code == 403,
      f"{still_there.status_code} {detail(still_there)}")

print("\n-- 8. a reset clears the lockout, and guessing a code is bounded --")
three_wrong = [login("carol@example.com", f"Wrong{i}").status_code for i in range(3)]
check("three wrong passwords lock Carol", three_wrong == [401, 401, 429], three_wrong)
check("Carol is locked", login("carol@example.com").status_code == 429)
patch_user("carol@example.com", last_reset_sent_at=0)
requested = client.post("/api/forgot-password", json={"email": "CAROL@example.com"})
check("Carol can request a reset while locked out", requested.status_code == 200,
      requested.status_code)
carol_code = (get_user("carol@example.com") or {}).get("reset_code", "")
reset = client.post(
    "/api/reset-password",
    json={"email": "carol@example.com", "code": carol_code, "new_password": "NewPassword1"},
)
check("the reset is accepted", reset.status_code == 200, detail(reset))
after_reset = get_user("carol@example.com") or {}
check("the lockout is cleared by the reset",
      not after_reset.get("failed_attempts") and not after_reset.get("lockout_until"),
      after_reset)
check("Carol can log in with the new password straight away",
      login("carol@example.com", "NewPassword1").status_code == 200)

# The used code is gone, so ask for a new one to test the guess limit.
patch_user("carol@example.com", last_reset_sent_at=0)
client.post("/api/forgot-password", json={"email": "carol@example.com"})
real_code = (get_user("carol@example.com") or {}).get("reset_code", "")
wrong_code = "000000" if real_code != "000000" else "111111"
attempts = [
    client.post("/api/reset-password",
                json={"email": "carol@example.com", "code": wrong_code,
                      "new_password": "NewPassword2"})
    for _ in range(5)
]
check("the first wrong code reports four attempts left",
      "4 attempt(s) remaining" in detail(attempts[0]), detail(attempts[0]))
check("wrong codes stop being answered after five",
      [a.status_code for a in attempts] == [400, 400, 400, 400, 429],
      [a.status_code for a in attempts])
check("the code is thrown away once the limit is reached",
      not (get_user("carol@example.com") or {}).get("reset_code"),
      (get_user("carol@example.com") or {}).get("reset_code"))
check("the real code no longer works after the limit",
      client.post("/api/reset-password",
                  json={"email": "carol@example.com", "code": real_code,
                        "new_password": "NewPassword3"}).status_code == 400)

print("\n-- the account list is a picker, not a directory --")
listing = client.get("/api/users", params={"user_id": 1})
check("GET /users answers", listing.status_code == 200, listing.status_code)
check("it carries no email addresses",
      all("email" not in user for user in listing.json()), listing.text[:200])
check("it still has what a picker needs",
      all({"user_id", "username", "profile_photo"} <= set(user)
          for user in listing.json()), listing.json()[:1])
check("a single account record carries no address either",
      "email" not in client.get("/api/users/1").json(),
      client.get("/api/users/1").json())

print("\n-- changing an address needs the password --")
check("without a password the request is rejected",
      client.post("/api/users/1/email-change",
                  json={"new_email": "alice.new@example.com"}).status_code == 422)
check("with the wrong password it is refused",
      client.post("/api/users/1/email-change",
                  json={"new_email": "alice.new@example.com",
                        "current_password": "WrongPassword1"}).status_code == 401)
accepted = client.post("/api/users/1/email-change",
                       json={"new_email": "alice.new@example.com",
                             "current_password": "Password123"})
check("with the right password it is accepted", accepted.status_code == 200,
      accepted.text[:200])
passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
if failures:
    print("failed: " + "; ".join(failures))
sys.exit(0 if passed == len(results) else 1)
