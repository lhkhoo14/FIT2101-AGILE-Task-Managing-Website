"""End-to-end checks for the deletion routes.

Drives the real FastAPI app against a temporary JSON database, so the tracked
server/data/server_database.json is never touched. Run it from the repository
root with:

    .venv\\Scripts\\python.exe server\\tests\\test_deletions.py

Every check is printed and the process exits non-zero if any failed. It is a
plain script rather than a pytest module because the repository has no test
runner configured.
"""
import json
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import database_manager  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from security import hash_password  # noqa: E402
from routes.projects import PRESET_ROLES  # noqa: E402
from main import app  # noqa: E402

TMP_DB = os.path.join(tempfile.mkdtemp(), "smoke_db.json")
database_manager.db_manager.db_path = TMP_DB

CARD = {"id": "task-5", "title": "Live task", "tags": ["api"], "assignee": None, "assignee_id": None}
DONE = {"id": "task-6", "title": "Done task", "completed_at": "2026-10-01"}
HOLD = {"id": "task-8", "title": "Held task", "tags": [], "assignee": "Bob", "assignee_id": 2}
EXTRA = {"id": "task-7", "title": "Extra task", "tags": [], "assignee": None, "assignee_id": None}
CAROL_CARD = {"id": "task-9", "title": "Old task", "tags": [], "assignee": "Carol", "assignee_id": 3}

SPRINT1 = {
    "id": "1", "name": "Sprint One", "status": "active", "created_by": 1,
    "start_date": "2026-01-01", "end_date": "2099-01-01", "members": [1, 2, 3],
    "kanban_state": {"backlog": [], "active": [CARD, HOLD, EXTRA], "review": [],
                     "completed": [DONE]},
}
SPRINT2 = {
    "id": "2", "name": "Sprint Two", "status": "ended", "created_by": 1,
    "start_date": "2025-01-01", "end_date": "2025-02-01", "members": [1, 2, 3],
    "kanban_state": {"backlog": [], "active": [CAROL_CARD], "review": [], "completed": []},
}
# Two more projects, each shaped for one of the permission checks below.

# Project 2 is stored the way the projects in server/data/server_database.json are:
# "roles": {} and no role_definitions at all. No permission can be granted on a
# record like that until ensure_member_fields() rebuilds the roles, so the first
# sprint request to touch it is what lets its members delete anything.
LEGACY_CARD = {"id": "task-11", "title": "Legacy task", "tags": [], "assignee": None,
               "assignee_id": None}
LEGACY_HOLD = {"id": "task-12", "title": "Legacy held task", "tags": [], "assignee": None,
               "assignee_id": None}
LEGACY_SPRINT = {
    "id": "3", "name": "Legacy sprint", "status": "active", "created_by": 1,
    "start_date": "2026-01-01", "end_date": "2099-01-01", "members": [1, 2],
    "kanban_state": {"backlog": [], "active": [LEGACY_CARD, LEGACY_HOLD], "review": [],
                     "completed": []},
}
LEGACY_PROJECT = {
    "project_id": 2, "name": "Legacy", "description": "", "creator": [1],
    "members": [1, 2], "roles": {}, "backlog": [], "sprints": [LEGACY_SPRINT],
}

# Project 3 has been set up the normal way, except that its one non-creator member
# (Dave) holds a custom role left without manage_tasks. Moving cards around is still
# his to do; dropping one is not.
VIEWER_CARD = {"id": "task-21", "title": "Viewer task", "tags": [], "assignee": None,
               "assignee_id": None}
VIEWER_OTHER = {"id": "task-22", "title": "Viewer other task", "tags": [], "assignee": None,
                "assignee_id": None}
VIEWER_SPRINT = {
    "id": "4", "name": "Viewer sprint", "status": "active", "created_by": 1,
    "start_date": "2026-01-01", "end_date": "2099-01-01", "members": [1, 4],
    "kanban_state": {"backlog": [], "active": [VIEWER_CARD, VIEWER_OTHER], "review": [],
                     "completed": []},
}
VIEWER_ROLE = {
    "colour": "#888888", "description": "Reads the board and moves cards.",
    "permissions": ["edit_sprints"], "conflicting_roles": [],
}
# Two custom roles for the "who may be removed" checks. Neither is a preset, so
# both rank below every preset role and are compared by what they grant: the
# Roster Admin's permissions are a strict subset of the Super Roster's.
ROSTER_ROLE = {
    "colour": "#f59e0b", "description": "Runs the roster.",
    "permissions": ["edit_sprints", "manage_members", "assign_roles"],
    "conflicting_roles": [],
}
SUPER_ROSTER_ROLE = {
    "colour": "#8b5cf6", "description": "Runs the roster and the roles.",
    "permissions": ["edit_sprints", "manage_members", "assign_roles", "manage_roles"],
    "conflicting_roles": [],
}
# A sprint stored without the project's Project Creator on it: this is the shape
# the repair in sprint_logic.ensure_leadership_membership() has to fix.
VIEWER_LONE_SPRINT = {
    "id": "5", "name": "Viewer only sprint", "status": "active", "created_by": 4,
    "start_date": "2026-01-01", "end_date": "2099-01-01", "members": [4],
    "kanban_state": {"backlog": [], "active": [], "review": [], "completed": []},
}
BETA_PROJECT = {
    "project_id": 3, "name": "Beta", "description": "", "creator": [1],
    "members": [1, 2, 4, 5], "contribute": [1, 2, 4, 5],
    "roles": {"Project Creator": [1], "Scrum Master": [], "Product Owner": [],
              "Manager": [], "Employee": [5], "Viewer": [], "Roster Admin": [4],
              "Super Roster": [2]},
    "role_definitions": {**PRESET_ROLES, "Viewer": VIEWER_ROLE,
                         "Roster Admin": ROSTER_ROLE, "Super Roster": SUPER_ROSTER_ROLE},
    "backlog": [], "sprints": [VIEWER_SPRINT, VIEWER_LONE_SPRINT],
}

# Which projects each account records itself as belonging to. Membership is really
# read from project["members"]; this is the mirrored list the user record keeps.
USER_PROJECTS = {1: [1, 2, 3], 2: [1, 2, 3], 3: [1], 4: [3], 5: [3]}

SEED = {
    "next_user_id": 6, "next_project_id": 4, "next_backlog_id": 50, "next_sprint_id": 5,
    "users": [
        {"user_id": i, "username": name, "email": f"{name.lower()}@example.com",
         "password": hash_password("Password123"), "projects": USER_PROJECTS[i]}
        for i, name in ((1, "Alice"), (2, "Bob"), (3, "Carol"), (4, "Dave"), (5, "Erin"))
    ],
    "projects": {
        "1": {
            "project_id": 1, "name": "Alpha", "description": "", "creator": [1],
            "members": [1, 2, 3], "contribute": [1, 2, 3],
            "roles": {"Project Creator": [1], "Scrum Master": [], "Product Owner": [],
                      "Manager": [], "Employee": [2, 3]},
            "role_definitions": PRESET_ROLES, "backlog": [], "sprints": [SPRINT1, SPRINT2],
        },
        "2": LEGACY_PROJECT,
        "3": BETA_PROJECT,
    },
}

with open(TMP_DB, "w") as handle:
    json.dump(SEED, handle)

client = TestClient(app)
results = []


def check(label, condition, detail=""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + ("" if condition else f"  <- {detail}"))


def db():
    with open(TMP_DB) as handle:
        return json.load(handle)


def board():
    return db()["projects"]["1"]["sprints"][0]["kanban_state"]


def history():
    response = client.get("/api/projects/1/history", params={"user_id": 1})
    return [entry["message"] for entry in response.json()]


def project(project_id):
    return db()["projects"][str(project_id)]


def project_board(project_id, sprint_index=0):
    return project(project_id)["sprints"][sprint_index]["kanban_state"]


def project_history(project_id, user_id=1):
    response = client.get(f"/api/projects/{project_id}/history", params={"user_id": user_id})
    return [entry["message"] for entry in response.json()]


def delete(path, body):
    return client.request("DELETE", path, json=body)


def post(path, body):
    return client.post(path, json=body)


def put(path, body):
    return client.put(path, json=body)


# --- task deletion -----------------------------------------------------------
response = delete("/api/projects/1/sprints/1/tasks/task-5", {"user_id": 2})
check("member deletes an active task (200)", response.status_code == 200, response.text)
check("card gone from the board", all(c["id"] != "task-5" for c in board()["active"]))
check("neighbouring cards survive", {c["id"] for c in board()["active"]} == {"task-8", "task-7"})
check("deletion reached Change History",
      any("deleted task Live task" in m for m in history()), history())

response = delete("/api/projects/1/sprints/1/tasks/task-6", {"user_id": 2})
check("completed task cannot be deleted (409)", response.status_code == 409, response.text)
response = delete("/api/projects/1/sprints/1/tasks/task-6", {"user_id": 4})
check("non-member cannot delete (403)", response.status_code == 403, response.text)
response = delete("/api/projects/1/sprints/2/tasks/task-9", {"user_id": 2})
check("task in an ended sprint cannot be deleted (409)", response.status_code == 409, response.text)

# --- a board save must not be able to delete a completed task ---------------
state = client.get("/api/projects/1/sprints/1/kanban", params={"user_id": 2}).json()
state["completed"] = []
response = put("/api/projects/1/sprints/1/kanban", {"user_id": 2, "state": state})
check("board save dropping a completed card refused (409)", response.status_code == 409,
      response.text)

state = client.get("/api/projects/1/sprints/1/kanban", params={"user_id": 2}).json()
state["active"] = [c for c in state["active"] if c["id"] != "task-7"]
response = put("/api/projects/1/sprints/1/kanban", {"user_id": 2, "state": state})
check("board save dropping an active card allowed (200)", response.status_code == 200, response.text)
check("that removal is audited too",
      any("deleted task Extra task" in m for m in history()), history())

# --- task deletion needs manage_tasks, not membership alone ------------------
# Project 2 is shaped like the projects already stored in the server database
# ("roles": {} and no role_definitions). The first sprint request to touch it
# rebuilds those roles, which is what allows its members to be permitted anything.
response = delete("/api/projects/2/sprints/3/tasks/task-11", {"user_id": 2})
check("legacy project: a member (Employee) deletes a task (200)",
      response.status_code == 200, response.text)
legacy = project(2)
check("legacy project gained a role map",
      legacy.get("roles", {}).get("Employee") == [2], legacy.get("roles"))
check("legacy project gained role_definitions",
      "Employee" in legacy.get("role_definitions", {}),
      sorted(legacy.get("role_definitions", {})))
check("its creator came back as Project Creator",
      legacy.get("roles", {}).get("Project Creator") == [1], legacy.get("roles"))
check("legacy board kept the other card",
      [c["id"] for c in project_board(2)["active"]] == ["task-12"], project_board(2)["active"])
check("legacy deletion reached Change History",
      any("deleted task Legacy task" in m for m in project_history(2)), project_history(2))

# Dave, on project 3, holds a custom role that was left without manage_tasks.
response = delete("/api/projects/3/sprints/4/tasks/task-21", {"user_id": 4})
check("custom role without manage_tasks cannot delete a task (403)",
      response.status_code == 403, response.text)
check("...and the task is still on the board",
      any(c["id"] == "task-21" for c in project_board(3)["active"]), project_board(3)["active"])

# The same rule on the board-save route: moving cards stays allowed, dropping one
# does not.
state = client.get("/api/projects/3/sprints/4/kanban", params={"user_id": 4}).json()
state["review"] = [state["active"].pop(0)]
response = put("/api/projects/3/sprints/4/kanban", {"user_id": 4, "state": state})
check("that user may still move a card between columns (200)",
      response.status_code == 200, response.text)

state = client.get("/api/projects/3/sprints/4/kanban", params={"user_id": 4}).json()
state["review"] = [c for c in state["review"] if c["id"] != "task-21"]
response = put("/api/projects/3/sprints/4/kanban", {"user_id": 4, "state": state})
check("board save dropping a card refused without manage_tasks (403)",
      response.status_code == 403, response.text)
check("...and that card survived the refusal",
      any(c["id"] == "task-21" for c in project_board(3)["review"]), project_board(3))

# --- sprint deletion ---------------------------------------------------------
response = delete("/api/projects/1/sprints/1", {"user_id": 3})
check("Employee without manage_sprints refused (403)", response.status_code == 403, response.text)
response = delete("/api/projects/1/sprints/2", {"user_id": 1})
check("completed sprint cannot be deleted (409)", response.status_code == 409, response.text)
response = delete("/api/projects/1/sprints/1", {"user_id": 1})
check("Project Creator deletes an active sprint (200)", response.status_code == 200, response.text)
check("sprint removed", [s["id"] for s in db()["projects"]["1"]["sprints"]] == ["2"])
check("sprint deletion reached Change History",
      any("deleted sprint Sprint One" in m for m in history()), history())

# --- member removal ----------------------------------------------------------
response = post("/api/projects/1/members/3/remove", {"user_id": 2})
check("Employee without manage_members refused (403)", response.status_code == 403, response.text)
response = post("/api/projects/1/members/1/remove", {"user_id": 1})
check("sole Project Creator cannot be removed (400)", response.status_code == 400, response.text)
response = post("/api/projects/1/members/3/remove", {"user_id": 1})
check("manage_members holder removes a member (200)", response.status_code == 200, response.text)
# CHANGE: named `alpha`, not `project`. The old name shadowed the project() helper
# defined above, so any later check that wanted to read a project by id crashed.
alpha = db()["projects"]["1"]
check("gone from members/contribute",
      3 not in alpha["members"] and 3 not in alpha["contribute"])
check("gone from every role", all(3 not in holders for holders in alpha["roles"].values()))
check("gone from sprint membership",
      all(3 not in sprint.get("members", []) for sprint in alpha["sprints"]))
held = alpha["sprints"][0]["kanban_state"]["active"][0]
check("their task survives, unassigned",
      held["id"] == "task-9" and held["assignee_id"] is None, held)
check("their contribution row is gone", "3" not in alpha.get("contributions", {}),
      sorted(alpha.get("contributions", {})))
check("removal reached Change History",
      any("removed Carol from the project" in m for m in history()), history())

# --- product backlog items ---------------------------------------------------
# POST /projects/{id}/backlog normalises tags and descriptions through
# sprint_logic, which was never imported in routes/projects.py: every call
# answered 500 with a NameError instead of storing the item.
response = post("/api/projects/1/backlog", {
    "user_id": 2, "title": "Live backlog item", "priority": "high",
    "tags": [" API ", "#api", "Urgent"], "description": "  trimmed  ",
})
check("an Employee adds a backlog item (201)", response.status_code == 201, response.text)
item = response.json() if response.status_code == 201 else {}
check("its tags come back normalised and de-duplicated",
      item.get("tags") == ["api", "urgent"], item)
check("its description is trimmed", item.get("description") == "trimmed", item)
check("it is stored on the project",
      any(entry["id"] == item.get("id") for entry in project(1)["backlog"]),
      project(1)["backlog"])

response = post("/api/projects/1/backlog", {
    "user_id": 2, "title": "Over-long", "priority": "low", "tags": [],
    "description": "x" * 1001,
})
check("an over-long description is refused (422)", response.status_code == 422, response.text)

# --- the project's leadership is on every sprint -----------------------------
# Sprint access is members-only, so the roles that own the sprint cycle
# (Project Creator, Scrum Master, Product Owner) are added to each sprint the
# server saves - otherwise they could not open the boards they are responsible
# for, and could not delete a sprint at all.
today = date.today()
response = post("/api/projects/1/sprints", {
    "user_id": 1, "name": "Board for the team", "details": "", "status": "active",
    "start_date": today.isoformat(), "end_date": (today + timedelta(days=7)).isoformat(),
    "tags": [], "members": [2],
})
check("a sprint is created (201)", response.status_code == 201, response.text)
created = response.json() if response.status_code == 201 else {}
check("the members it was ticked for are kept", 2 in created.get("members", []), created)
check("its Project Creator is on it without being ticked",
      1 in created.get("members", []), created)

# The same rule for a sprint that was stored before the leadership existed: the
# first request to touch the project repairs it, and the repair is written back.
client.get("/api/projects/3/sprints", params={"user_id": 4})
lone = next((s for s in project(3)["sprints"] if str(s["id"]) == "5"), None)
check("a stored sprint gains its Project Creator on the next request",
      lone is not None and 1 in lone.get("members", []), lone)

# --- who may be removed: preset rank, then permission sets --------------------
# Dave holds a custom role granting manage_members, which is what lets him reach
# the checks below at all; the two rules then decide whose Remove he is offered.
# (Removing the Project Creator is refused earlier still, by the sole-creator
# guard proven above, so the rank rule is exercised against an Employee.)
ranking_message = "ranks equal to or above yours"

response = post("/api/projects/3/members/4/remove", {"user_id": 4})
check("a member cannot remove themselves (403)",
      response.status_code == 403 and ranking_message in response.text, response.text)

response = post("/api/projects/3/members/5/remove", {"user_id": 4})
check("a custom role cannot remove a preset role above it (403)",
      response.status_code == 403 and ranking_message in response.text, response.text)
check("...and that member is still on the project", 5 in project(3)["members"],
      project(3)["members"])

# Equal rank (neither role is a preset), so the permission sets decide: the
# Super Roster's are a strict superset of the Roster Admin's.
response = post("/api/projects/3/members/4/remove", {"user_id": 2})
check("at equal rank the strictly larger permission set wins (200)",
      response.status_code == 200, response.text)
check("...and the usual cascade ran", 4 not in project(3)["members"], project(3)["members"])

# --- account deletion --------------------------------------------------------
response = post("/api/users/3/delete", {"password": "WrongPassword1"})
check("wrong password refused (401)", response.status_code == 401, response.text)
response = post("/api/users/1/delete", {"password": "Password123"})
check("sole Project Creator cannot delete their account (409)", response.status_code == 409,
      response.text)
response = post("/api/users/3/delete", {"password": "Password123"})
check("member deletes their own account (200)", response.status_code == 200, response.text)
check("user record gone", all(u["user_id"] != 3 for u in db()["users"]))
check("their work is kept, unassigned",
      db()["projects"]["1"]["sprints"][0]["kanban_state"]["active"][0]["assignee_id"] is None)

# --- project deletion --------------------------------------------------------
response = delete("/api/projects/1", {"user_id": 2})
check("delete_project holder required (403)", response.status_code == 403, response.text)
response = delete("/api/projects/1", {"user_id": 1})
check("Project Creator deletes the project (200)", response.status_code == 200, response.text)
remaining = db()
check("project gone", "1" not in remaining["projects"])
check("accounts survive, dangling project id pruned",
      all(1 not in (u.get("projects") or []) for u in remaining["users"]),
      [u["projects"] for u in remaining["users"]])

if __name__ == "__main__":
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
