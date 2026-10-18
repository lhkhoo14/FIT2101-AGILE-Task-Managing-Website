"""End-to-end checks that boot the real API server and drive it over HTTP.

Unlike test_deletions.py, which uses FastAPI's in-process TestClient, this
starts an actual uvicorn server on a free port and sends real requests, so it
also proves the app boots, that the routes are mounted under /api, and that
every response is JSON.

The requests use the same paths and payloads as the browser's ServerData client
(see src/backend/server_data.py), so a client/server contract drift shows up
here as a failing check.

The server runs against a temporary JSON database seeded in this script, so the
tracked server/data/server_database.json is never opened - its hash is compared
before and after to prove it.

Run it from the repository root with:

    .venv\\Scripts\\python.exe server\\tests\\test_live_api.py

Every check is printed and the process exits non-zero if any failed. It is a
plain script rather than a pytest module because the repository has no test
runner configured.
"""
import base64
import hashlib
import json
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

import httpx

# Resolved from this file, so the script runs from any working directory.
TESTS_DIR = pathlib.Path(__file__).resolve().parent
SERVER = TESTS_DIR.parent                     # the server package
REPO = SERVER.parent                          # the repository root
TRACKED_DB = SERVER / "data" / "server_database.json"

sys.path.insert(0, str(SERVER))
from security import hash_password  # noqa: E402

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

TMP = pathlib.Path(tempfile.mkdtemp(prefix="smoke_"))
DB = TMP / "smoke_db.json"

SEED = {
    "next_user_id": 3,
    "next_project_id": 1,
    "next_backlog_id": 1,
    "next_sprint_id": 1,
    # Seeded accounts are established users. Login rejects accounts that have
    # not completed the 6-character email verification, so they are verified here.
    "users": [
        {"user_id": 1, "username": "Alice", "email": "alice@example.com",
         "password": hash_password("Password123"), "is_verified": True, "projects": []},
        {"user_id": 2, "username": "Bob", "email": "bob@example.com",
         "password": hash_password("Password123"), "is_verified": True, "projects": []},
    ],
    "projects": {},
}
DB.write_text(json.dumps(SEED), encoding="utf-8")

# The app builds its DatabaseManager at import time from DB_PATH, so the wrapper
# module points both the constant and the singleton at the temp file before
# importing main (the same trick test_deletions.py uses for the singleton).
WRAPPER = TMP / "smoke_app.py"
WRAPPER.write_text(
    "import sys\n"
    f"sys.path.insert(0, {str(SERVER)!r})\n"
    "import database_manager\n"
    f"database_manager.DB_PATH = {str(DB)!r}\n"
    f"database_manager.db_manager.db_path = {str(DB)!r}\n"
    # Never let a developer's real Brevo key make the test run send mail.
    "import os\n"
    "os.environ.pop('BREVO_API_KEY', None)\n"
    "from main import app  # noqa: F401\n",
    encoding="utf-8",
)

results = []
failures = []


def check(label, condition, detail: object = ""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + ("" if condition else f"  <- {detail}"))
    if not condition:
        failures.append(label)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


tracked_before = sha(TRACKED_DB)

port = free_port()
log_path = TMP / "server.log"
log = open(log_path, "w", encoding="utf-8")
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "smoke_app:app",
     "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
    cwd=str(TMP), stdout=log, stderr=subprocess.STDOUT,
)

base = f"http://127.0.0.1:{port}"
client = httpx.Client(base_url=base, timeout=15.0)

booted = False
for _ in range(100):
    try:
        if client.get("/health").status_code == 200:
            booted = True
            break
    except Exception:
        time.sleep(0.2)
check("server boots and /health answers 200", booted)

try:
    if not booted:
        raise SystemExit(1)

    health = client.get("/health").json()
    check("/health reports ok", health == {"status": "ok"}, health)

    # --- auth (register, login, directory) --------------------------------
    r = client.post("/api/register", json={"username": "Carol", "email": "carol@example.com",
                                          "password": "Password123"})
    check("POST /api/register -> 201", r.status_code == 201, r.text[:200])
    carol_id = r.json().get("user_id")

    r = client.post("/api/login", json={"email": "alice@example.com", "password": "Password123"})
    check("POST /api/login -> 200", r.status_code == 200, r.text[:200])
    alice_id = r.json().get("user_id") or 1

    r = client.post("/api/login", json={"email": "alice@example.com", "password": "wrong"})
    check("POST /api/login with a bad password -> 401", r.status_code == 401, r.status_code)

    r = client.get("/api/users", params={"user_id": alice_id})
    check("GET /api/users -> 200 list", r.status_code == 200 and isinstance(r.json(), list),
          r.text[:200])

    r = client.get(f"/api/users/{alice_id}")
    check("GET /api/users/{id} -> 200", r.status_code == 200, r.text[:200])

    # --- project ----------------------------------------------------------
    r = client.post("/api/projects", json={"user_id": alice_id, "name": "Smoke",
                                           "description": "live run"})
    check("POST /api/projects -> 201", r.status_code == 201, r.text[:200])
    project_id = (r.json().get("project") or {}).get("project_id")

    r = client.get(f"/api/users/{alice_id}/projects")
    names = [p.get("name") for p in r.json()] if r.status_code == 200 else []
    check("GET /api/users/{id}/projects lists it", "Smoke" in names, r.text[:200])

    r = client.get(f"/api/projects/{project_id}", params={"user_id": alice_id})
    check("GET /api/projects/{id} -> 200", r.status_code == 200, r.text[:200])

    # --- members ----------------------------------------------------------
    r = client.post(f"/api/projects/{project_id}/members",
                    json={"user_id": alice_id, "username": "Bob"})
    check("POST /projects/{id}/members -> 2xx", r.status_code in (200, 201), r.text[:200])

    r = client.get(f"/api/projects/{project_id}/members", params={"user_id": alice_id})
    members = r.json().get("members", []) if r.status_code == 200 else []
    check("GET /projects/{id}/members includes Bob", 2 in members, r.text[:200])

    # --- roles: create, update, assign, remove, delete --------------------
    r = client.post(f"/api/projects/{project_id}/roles",
                    json={"user_id": alice_id, "name": "QA", "colour": "#22c55e",
                          "description": "Checks the work",
                          "permissions": ["manage_tasks"], "conflicting_roles": []})
    check("POST /projects/{id}/roles (create) -> 2xx", r.status_code in (200, 201), r.text[:200])

    r = client.get(f"/api/projects/{project_id}", params={"user_id": alice_id})
    roles = (r.json().get("roles") or {}) if r.status_code == 200 else {}
    check("the new role is stored on the project", "QA" in roles, list(roles))

    r = client.put(f"/api/projects/{project_id}/roles/QA",
                   json={"user_id": alice_id, "colour": "#0ea5e9", "description": "QA work",
                         "permissions": ["manage_tasks"], "conflicting_roles": []})
    check("PUT /projects/{id}/roles/QA -> 200", r.status_code == 200, r.text[:200])

    r = client.get(f"/api/projects/{project_id}/roles/QA/members", params={"user_id": alice_id})
    check("GET /projects/{id}/roles/QA/members -> 200", r.status_code == 200, r.text[:200])

    r = client.post(f"/api/projects/{project_id}/roles/assign",
                    json={"user_id": alice_id, "target_user_id": 2, "role_name": "QA"})
    check("POST /roles/assign -> 200", r.status_code == 200, r.text[:200])

    r = client.post(f"/api/projects/{project_id}/roles/QA/remove",
                    json={"user_id": alice_id, "target_user_id": 2})
    check("POST /roles/QA/remove -> 200", r.status_code == 200, r.text[:200])

    r = client.request("DELETE", f"/api/projects/{project_id}/roles/QA",
                       json={"user_id": alice_id})
    check("DELETE /projects/{id}/roles/QA -> 200", r.status_code == 200, r.text[:200])

    # --- product backlog --------------------------------------------------
    r = client.post(f"/api/projects/{project_id}/backlog",
                    json={"user_id": alice_id, "title": "Smoke story", "tags": ["api"],
                          "priority": "High", "description": "from the live run"})
    check("POST /projects/{id}/backlog -> 2xx", r.status_code in (200, 201), r.text[:200])

    r = client.get(f"/api/projects/{project_id}/backlog", params={"user_id": alice_id})
    backlog = r.json() if r.status_code == 200 else []
    check("GET /projects/{id}/backlog -> 200 with the item", len(backlog) == 1, r.text[:200])
    backlog_id = backlog[0].get("id") if backlog else None

    # --- sprint: create (the reported bug), read, board --------------------
    r = client.post(f"/api/projects/{project_id}/sprints",
                    json={"user_id": alice_id, "name": "Smoke sprint", "details": "",
                          "status": "active", "start_date": "2026-01-01",
                          "end_date": "2026-12-31", "priority": "High", "tags": ["api"],
                          "members": [alice_id, 2]})
    check("POST /projects/{id}/sprints (create) -> 201", r.status_code == 201, r.text[:200])
    sprint_id = r.json().get("id")

    r = client.get(f"/api/projects/{project_id}/sprints", params={"user_id": alice_id})
    sprints = r.json() if r.status_code == 200 else []
    check("GET /projects/{id}/sprints lists it",
          any(str(s.get("id")) == str(sprint_id) for s in sprints), r.text[:200])

    r = client.post(f"/api/projects/{project_id}/sprints/{sprint_id}/backlog",
                    json={"user_id": alice_id, "backlog_id": backlog_id})
    check("POST /sprints/{id}/backlog moves the story in -> 200", r.status_code == 200,
          r.text[:200])

    r = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/kanban",
                   params={"user_id": alice_id})
    state = r.json() if r.status_code == 200 else {}
    check("GET /sprints/{id}/kanban -> 200", r.status_code == 200, r.text[:200])

    r = client.get(f"/api/projects/{project_id}/kanban-states", params={"user_id": alice_id})
    check("GET /projects/{id}/kanban-states -> 200", r.status_code == 200, r.text[:200])

    task = (state.get("backlog") or state.get("active") or [None])[0]
    task_id = task.get("id") if task else None
    check("the moved story landed on the board", task_id is not None, json.dumps(state)[:200])

    r = client.put(f"/api/projects/{project_id}/sprints/{sprint_id}/kanban",
                   json={"user_id": alice_id, "state": state})
    check("PUT /sprints/{id}/kanban (save board) -> 200", r.status_code == 200, r.text[:200])

    # --- task actions -----------------------------------------------------
    r = client.post(f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/time-log",
                    json={"user_id": alice_id, "action": "start"})
    check("POST time-log start -> 200", r.status_code == 200, r.text[:200])
    r = client.post(f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/time-log",
                    json={"user_id": alice_id, "action": "stop"})
    check("POST time-log stop -> 200", r.status_code == 200, r.text[:200])

    # --- activity: history, contributions ---------------------------------
    r = client.post(f"/api/projects/{project_id}/history",
                    json={"user_id": alice_id, "action": "created",
                          "message": "Smoke story created", "sprint_id": str(sprint_id),
                          "sprint_name": "Smoke sprint", "task_id": str(task_id),
                          "task_title": "Smoke story"})
    check("POST /projects/{id}/history (record change) -> 201", r.status_code == 201, r.text[:200])

    r = client.get(f"/api/projects/{project_id}/history", params={"user_id": alice_id})
    check("GET /projects/{id}/history -> 200 with the entry",
          r.status_code == 200 and len(r.json()) >= 1, r.text[:200])

    r = client.get(f"/api/projects/{project_id}/contributions", params={"user_id": alice_id})
    check("GET /projects/{id}/contributions -> 200", r.status_code == 200, r.text[:200])
    contrib = r.json() if r.status_code == 200 else {}
    members_stats = contrib.get("members", []) if isinstance(contrib, dict) else []
    alice_stats = next((m for m in members_stats if m.get("user_id") == alice_id), {})
    # US-21: the session is recorded even when it lasted no measurable time, so
    # the work_logs entry is the proof the log reached the contribution table.
    check("contributions credits the logged session to its logger",
          bool(alice_stats.get("work_logs")), json.dumps(alice_stats)[:300])

    # --- task removal paths ------------------------------------------------
    # The card has a logged session by now, so the server refuses to send it
    # back to the product backlog (the board shows the same rule up front).
    r = client.post(f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}"
                    "/return-to-backlog", json={"user_id": alice_id})
    check("return-to-backlog is refused once work is logged (409)", r.status_code == 409,
          f"{r.status_code} {r.text[:160]}")

    # A second story with no logged work is the happy path.
    r = client.post(f"/api/projects/{project_id}/backlog",
                    json={"user_id": alice_id, "title": "Smoke story two", "tags": [],
                          "priority": "Low", "description": ""})
    story_two_id = r.json().get("id") if r.status_code in (200, 201) else None
    client.post(f"/api/projects/{project_id}/sprints/{sprint_id}/backlog",
                json={"user_id": alice_id, "backlog_id": story_two_id})
    r = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/kanban",
                   params={"user_id": alice_id})
    board = r.json() if r.status_code == 200 else {}
    story_two_task = next(
        (t for col in board.values() if isinstance(col, list) for t in col
         if t.get("title") == "Smoke story two"), None,
    )
    check("the second story reached the board", story_two_task is not None,
          json.dumps(board)[:200])

    r = client.post(f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/"
                    f"{(story_two_task or {}).get('id')}/return-to-backlog",
                    json={"user_id": alice_id})
    check("return-to-backlog works for a task with no logged work -> 200",
          r.status_code == 200, r.text[:200])

    r = client.request("DELETE",
                       f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}",
                       json={"user_id": alice_id})
    check("DELETE /sprints/{id}/tasks/{task} -> 200", r.status_code == 200, r.text[:200])

    # Ending a sprint then deleting it: a completed sprint is kept as the record
    # of what the team finished, so the delete is refused.
    r = client.patch(f"/api/projects/{project_id}/sprints/{sprint_id}/status",
                     json={"user_id": alice_id, "status": "ended"})
    check("PATCH /sprints/{id}/status (end sprint) -> 200", r.status_code == 200, r.text[:200])

    r = client.request("DELETE", f"/api/projects/{project_id}/sprints/{sprint_id}",
                       json={"user_id": alice_id})
    check("deleting a completed sprint is refused (409)", r.status_code == 409,
          f"{r.status_code} {r.text[:160]}")

    # A second, still-active sprint can be deleted. Its dates must be in the
    # future: validate_sprint_dates refuses a sprint that starts in the past.
    r = client.post(f"/api/projects/{project_id}/sprints",
                    json={"user_id": alice_id, "name": "Doomed sprint", "details": "",
                          "status": "active", "start_date": "2027-01-01",
                          "end_date": "2027-03-01", "priority": "Low", "tags": [],
                          "members": [alice_id]})
    check("a second sprint can be created -> 201", r.status_code == 201,
          f"{r.status_code} {r.text[:160]}")
    doomed_id = r.json().get("id") if r.status_code == 201 else None
    r = client.request("DELETE", f"/api/projects/{project_id}/sprints/{doomed_id}",
                       json={"user_id": alice_id})
    check("DELETE an active sprint -> 200", r.status_code == 200,
          f"{r.status_code} {r.text[:160]}")

    # --- account settings -------------------------------------------------
    r = client.get(f"/api/users/{alice_id}/settings")
    check("GET /users/{id}/settings -> 200 dict",
          r.status_code == 200 and isinstance(r.json(), dict), r.text[:200])

    r = client.patch(f"/api/users/{alice_id}/profile", json={"username": "Alice B"})
    check("PATCH /users/{id}/profile -> 200", r.status_code == 200, r.text[:200])
    # The picture is stored in its own table and served from its own URL, so the
    # shared state document never carries the image bytes.
    photo = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode("ascii")
    r = client.patch(f"/api/users/{alice_id}/profile",
                     json={"username": "Alice B", "profile_photo": photo})
    check("PATCH profile stores a photo -> 200", r.status_code == 200, r.text[:200])
    photo_url = str(r.json().get("profile_photo", ""))
    check("the response carries an absolute avatar URL",
          photo_url.startswith("http") and f"/users/{alice_id}/avatar" in photo_url, photo_url)

    r = client.get(f"/api/users/{alice_id}")
    check("GET /users/{id} carries the avatar URL, not the image",
          f"/users/{alice_id}/avatar" in str(r.json().get("profile_photo")), r.text[:200])

    r = client.get(f"/api/users/{alice_id}/avatar")
    check("GET the avatar -> 200 image/png",
          r.status_code == 200 and r.headers.get("content-type", "").startswith("image/png"),
          r.status_code)
    check("the avatar bytes come back unchanged", r.content == PNG_1PX, len(r.content))
    etag = r.headers.get("etag") or ""
    r = client.get(f"/api/users/{alice_id}/avatar", headers={"If-None-Match": etag})
    check("a cached avatar revalidates with 304", r.status_code == 304, r.status_code)

    r = client.get("/api/users", params={"user_id": alice_id})
    check("the directory lists avatar URLs instead of image bytes",
          "/users/" in r.text and "data:image" not in r.text, r.text[:200])

    r = client.patch(f"/api/users/{alice_id}/profile", json={"profile_photo": ""})
    check("removing the photo -> 200", r.status_code == 200, r.text[:200])
    r = client.get(f"/api/users/{alice_id}/avatar")
    check("the removed avatar is gone (404)", r.status_code == 404, r.status_code)
    r = client.get(f"/api/users/{alice_id}")
    check("the account falls back to the default picture",
          str(r.json().get("profile_photo", "")).endswith("default-profile.svg"), r.text[:200])
    check("the state document holds no inline data URL",
          "data:image" not in DB.read_text(encoding="utf-8"), "base64 found in the state")

    r = client.post(f"/api/users/{alice_id}/password",
                    json={"current_password": "Password123", "new_password": "Password456"})
    check("POST /users/{id}/password -> 200", r.status_code == 200, r.text[:200])

    r = client.post("/api/login", json={"email": "alice@example.com", "password": "Password456"})
    check("the new password works for login", r.status_code == 200, r.text[:200])

    r = client.post(f"/api/users/{alice_id}/email-change", json={"new_email": "alice.b@example.com"})
    check("POST /users/{id}/email-change -> 200", r.status_code == 200, r.text[:200])

    # --- removals ---------------------------------------------------------
    r = client.post(f"/api/projects/{project_id}/members/2/remove", json={"user_id": alice_id})
    check("POST /members/{id}/remove -> 200", r.status_code == 200, r.text[:200])

    r = client.post(f"/api/users/{carol_id}/delete", json={"password": "Password123"})
    check("POST /users/{id}/delete (account) -> 200", r.status_code == 200, r.text[:200])

    r = client.request("DELETE", f"/api/projects/{project_id}", json={"user_id": alice_id})
    check("DELETE /projects/{id} -> 200", r.status_code == 200, r.text[:200])

    r = client.get(f"/api/projects/{project_id}", params={"user_id": alice_id})
    check("the deleted project is gone (404)", r.status_code == 404, r.status_code)

finally:
    client.close()
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()

# --- server-side health ---------------------------------------------------
server_log = log_path.read_text(encoding="utf-8", errors="replace")
check("the server log has no traceback", "Traceback" not in server_log, server_log[-1500:])
check("the tracked database was never opened", sha(TRACKED_DB) == tracked_before)

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
if failures:
    print("failed: " + "; ".join(failures))
sys.exit(0 if passed == len(results) else 1)
