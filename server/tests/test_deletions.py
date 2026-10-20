"""End-to-end checks for the deletion routes.

Drives the real FastAPI app against a temporary JSON database, so the tracked
server/data/server_database.json is never touched. Run it from the repository
root with:

    .venv\\Scripts\\python.exe server\\tests\\test_deletions.py

Every check is printed and the process exits non-zero if any failed. It is a
plain script rather than a pytest module because the repository has no test
runner configured.
"""
import ast
import builtins
import json
import os
import re
import sys
import tempfile
from datetime import date, timedelta

os.environ.pop("DATABASE_URL", None)
# Keep the mailer offline: a real key in the environment would otherwise make
# registration and password-reset checks send genuine email.
os.environ.pop("BREVO_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# Repository root, for the static checks on the browser's own modules.
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

import database_manager  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from security import hash_password  # noqa: E402
from routes.projects import PRESET_ROLES  # noqa: E402
from dependencies import SINGLETON_PRESET_ROLES as SERVER_SINGLETONS  # noqa: E402
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


def check(label, condition, detail: object = ""):
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

# ---------------------------------------------------------------------------
# Ending a sprint needs manage_sprints, like deleting one.
#
# Ending is irreversible - it freezes the board and settles the figures the
# burndown is computed from - so plain membership is not enough. Sprint 2 is
# already ended here, so the permitted calls below leave the fixtures intact.
# ---------------------------------------------------------------------------
response = client.patch("/api/projects/1/sprints/1/status",
                        json={"user_id": 3, "status": "ended"})
check("an Employee without manage_sprints cannot end a sprint (403)",
      response.status_code == 403, response.text)
check("...and the sprint is untouched",
      next(s for s in db()["projects"]["1"]["sprints"] if s["id"] == "1")["status"] == "active")

response = client.patch("/api/projects/1/sprints/2/status",
                        json={"user_id": 1, "status": "ended"})
check("a manage_sprints holder can end a sprint (200)", response.status_code == 200,
      response.text)

response = client.patch("/api/projects/1/sprints/2/status",
                        json={"user_id": 1, "status": "active"})
check("an ended sprint cannot be reopened (409)", response.status_code == 409, response.text)

# A preset's permission list cannot be rewritten through the update route: only
# the roles the Roles page lets you edit may be edited. Employee is a preset, so
# emptying it here would silently strip every holder of manage_tasks.
response = client.put("/api/projects/1/roles/Employee",
                      json={"user_id": 1, "colour": "#000", "description": "",
                            "permissions": [], "conflicting_roles": []})
check("a preset role cannot be modified (400)", response.status_code == 400, response.text)
check("...and its permissions are intact",
      "manage_tasks" in (db()["projects"]["1"].get("role_definitions", {})
                         .get("Employee", {}).get("permissions", [])),
      db()["projects"]["1"].get("role_definitions", {}).get("Employee"))

# --- editing the project needs edit_project --------------------------------
# The description and the status are both edits, and both are gated on
# edit_project: Project Creator, Scrum Master and Product Owner only.
response = client.put("/api/projects/1/description",
                      json={"user_id": 2, "description": "Employees cannot edit this."})
check("an Employee cannot edit the description (403)",
      response.status_code == 403, response.text)

response = client.put("/api/projects/1/description",
                      json={"user_id": 1, "description": "Owned by the creator."})
check("the Project Creator can edit the description (200)",
      response.status_code == 200, response.text)
check("the edit is attributed", bool(response.json().get("last_edited_by")), response.text)

response = client.patch("/api/projects/1/status", json={"user_id": 2, "status": "completed"})
check("an Employee cannot complete the project (403)",
      response.status_code == 403, response.text)

response = client.patch("/api/projects/1/status", json={"user_id": 1, "status": "completed"})
check("the Project Creator can complete it (200)",
      response.status_code == 200, response.text)

response = client.patch("/api/projects/1/status", json={"user_id": 1, "status": "active"})
check("and can reopen it again (200)", response.status_code == 200, response.text)

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

# --- creating a sprint needs manage_sprints --------------------------------
# Employee (user 2) is still a member of project 1 but holds only edit_sprints
# and manage_tasks, so the create endpoint refuses them. Manager and above hold
# manage_sprints, which is what the Project Creator uses below.
response = post("/api/projects/1/sprints", {
    "user_id": 2, "name": "Employee sprint", "details": "", "status": "active",
    "start_date": "2026-01-01", "end_date": "2099-01-01", "priority": "medium",
    "members": [2],
})
check("an Employee cannot create a sprint (403)", response.status_code == 403, response.text)
check("...and none was added", len(db()["projects"]["1"]["sprints"]) == 1,
      db()["projects"]["1"]["sprints"])

response = post("/api/projects/2/sprints", {
    "user_id": 1, "name": "Leadership sprint", "details": "",
    "status": "active", "start_date": "2026-01-01", "end_date": "2099-01-01",
    "priority": "medium", "members": [1],
})
check("the Project Creator can create a sprint (201)",
      response.status_code == 201, response.text)


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
# main's US-38 semantics: the account goes, its role assignments and card
# assignments are cleared, and a project where the user was the last member is
# cleaned up. A sole Project Creator is therefore no longer refused - that case
# is asserted at the end of this file, because deleting user 1 hands the top
# role on and later checks still need that account.
response = post("/api/users/3/delete", {"password": "WrongPassword1"})
check("wrong password refused (401)", response.status_code == 401, response.text)
response = post("/api/users/3/delete", {"password": "Password123"})
check("member deletes their own account (200)", response.status_code == 200, response.text)
check("user record gone", all(u["user_id"] != 3 for u in db()["users"]))
check("their work is kept, unassigned",
      db()["projects"]["1"]["sprints"][0]["kanban_state"]["active"][0]["assignee_id"] is None)

# --- the preset table is shared, the presets are protected -------------------
# Project 2 is the legacy record used above ("roles": {} and no role_definitions).
# Repairing it used to hand the project the module-level PRESET_ROLES table
# itself, so a custom role created here was written into that shared table and
# leaked into every other project - and into the definitions handed to the next
# project that needed repairing.
response = post("/api/projects/2/roles",
                {"user_id": 1, "name": "Auditor", "colour": "#123456",
                 "description": "Reads the board.", "permissions": ["edit_sprints"]})
check("a custom role can be created in the legacy project (201)",
      response.status_code == 201, response.text)
check("the shared preset table was not written to",
      "Auditor" not in PRESET_ROLES, sorted(PRESET_ROLES))
check("the other project's definitions are untouched",
      "Auditor" not in project(1).get("role_definitions", {}),
      sorted(project(1).get("role_definitions", {})))
check("the role landed in its own project",
      "Auditor" in project(2).get("role_definitions", {}),
      sorted(project(2).get("role_definitions", {})))

# The presets are what every permission is defined against, so the API refuses to
# delete one - the same set the Roles page refuses in the browser.
response = delete("/api/projects/2/roles/Employee", {"user_id": 1})
check("a preset role cannot be deleted through the API (400)",
      response.status_code == 400, response.text)
response = delete("/api/projects/2/roles/Auditor", {"user_id": 1})
check("a custom role still deletes (200)", response.status_code == 200, response.text)


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

# --- account deletion: the Project Creator's own account ---------------------
# Handing ownership on instead of refusing: the account and its assignments go,
# the project stays for everyone else, and the top role passes to a member.
creator = next(u for u in db()["users"] if u["user_id"] == 1)
creator_name = str(creator.get("username") or "").lower()
response = post("/api/users/1/delete", {"password": "Password123"})
check("a sole Project Creator may delete their account (200)", response.status_code == 200,
      response.text)
final = db()
check("their user record is gone", all(u["user_id"] != 1 for u in final["users"]))
check("no role still lists them",
      all(str(holder) != "1"
          for holders in project(3)["roles"].values() if isinstance(holders, list)
          for holder in holders),
      project(3)["roles"])
check("the project survives for the others", 1 not in project(3)["members"],
      project(3)["members"])
check("the top role passed to a remaining member",
      len(project(3)["roles"].get("Project Creator", [])) == 1
      and str(project(3)["roles"]["Project Creator"][0]) in [str(m) for m in project(3)["members"]],
      project(3)["roles"].get("Project Creator"))
check("no card is still assigned to them",
      all(str(task.get("assignee_id")) != "1"
          and str(task.get("assignee") or "").lower() != creator_name
          for project_ in final["projects"].values()
          for sprint in (project_.get("sprints") or [])
          for column in ("backlog", "active", "review", "completed")
          for task in ((sprint.get("kanban_state") or {}).get(column) or [])),
      "a card is still assigned to the deleted account")


# ---------------------------------------------------------------------------
# The browser's own data layer.
#
# PyScript runs src/backend/server_data.py, so every method the views call has
# to be a member of ServerData *in that file*. A stray duplicate `class Project:`
# once terminated ServerData halfway down, which left record_change,
# create_project_role, get_role_members and the rest defined but unreachable -
# py_compile was happy, the methods were plainly in the file by grep, and every
# page that used them failed at run time with
# "'ServerData' object has no attribute ...". These checks are static, so they
# run here without a browser.
# ---------------------------------------------------------------------------
SERVER_DATA = os.path.join(PROJECT_ROOT, "src", "backend", "server_data.py")
CLIENT_DIRS = (os.path.join(PROJECT_ROOT, "src", "backend"),)
CLIENT_OWNERS = ("db", "server_data", "data", "store")
DICT_METHODS = {"get", "items", "keys", "values", "pop", "update", "setdefault"}


def client_module_audit():
    """Returns (top-level class names, ServerData members, orphan defs, called)."""
    with open(SERVER_DATA, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    class_names = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    orphans = [
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    members = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ServerData":
            members += [
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]

    called = set()
    for root in CLIENT_DIRS:
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                if os.path.abspath(path) == os.path.abspath(SERVER_DATA):
                    continue
                with open(path, encoding="utf-8") as handle:
                    try:
                        module = ast.parse(handle.read())
                    except SyntaxError:
                        continue
                for node in ast.walk(module):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    if not isinstance(func, ast.Attribute):
                        continue
                    owner = func.value
                    if (
                        isinstance(owner, ast.Name)
                        and owner.id in CLIENT_OWNERS
                        and func.attr not in DICT_METHODS
                    ):
                        called.add(func.attr)

    return class_names, members, orphans, called


CLASS_NAMES, SERVER_MEMBERS, ORPHAN_DEFS, CALLED_METHODS = client_module_audit()

check("the browser's server_data.py defines Project exactly once",
      CLASS_NAMES.count("Project") == 1,
      f"classes found: {CLASS_NAMES}")
check("the browser's server_data.py defines ServerData exactly once",
      CLASS_NAMES.count("ServerData") == 1,
      f"classes found: {CLASS_NAMES}")
check("no method in server_data.py sits outside a class",
      not ORPHAN_DEFS,
      f"module-level defs: {ORPHAN_DEFS}")
check("ServerData has no method defined twice",
      len(SERVER_MEMBERS) == len(set(SERVER_MEMBERS)),
      f"duplicates: {sorted({m for m in SERVER_MEMBERS if SERVER_MEMBERS.count(m) > 1})}")

MISSING_ON_SERVER_DATA = sorted(CALLED_METHODS - set(SERVER_MEMBERS))
check("every ServerData method the views call is a member of ServerData",
      not MISSING_ON_SERVER_DATA,
      f"called but not defined on ServerData: {MISSING_ON_SERVER_DATA}")

for name in ("record_change", "get_change_history", "get_contributions",
             "log_task_time", "get_project_member_users", "create_project_role",
             "get_role_members", "remove_project_member", "delete_account"):
    check(f"ServerData.{name} is reachable from the browser",
          name in SERVER_MEMBERS)


# ---------------------------------------------------------------------------
# Single-seat preset roles.
#
# Project Creator, Scrum Master and Product Owner are leadership posts, so a
# project may only ever have one holder of each. Beta (project 3) starts with
# all three empty and Alice (1) is its Project Creator, so she holds
# manage_roles and can hand them out.
# ---------------------------------------------------------------------------
def assign_role(project_id, actor, target, role):
    return post(f"/api/projects/{project_id}/roles/assign",
                {"user_id": actor, "target_user_id": target, "role_name": role})


# These checks build their own project: by the time this section runs the cases
# above have deleted accounts and passed project 3 to another owner, so nothing
# in the seed can be relied on. Bob (2) and whichever account follows him are
# the survivors of that sequence.
owner_id = 2
other_user = next(user for user in db()["users"] if user["user_id"] != owner_id)
other_id = other_user["user_id"]
other_name = other_user["username"]

created = post("/api/projects", {"user_id": owner_id, "name": "Single seat",
                                 "description": "single-seat role checks"})
fixture = created.json().get("project", {})
fixture_id = fixture.get("project_id")
check("the single-seat fixture project was created (201)",
      created.status_code == 201 and bool(fixture_id), created.text)

joined = post(f"/api/projects/{fixture_id}/members",
              {"user_id": owner_id, "username": other_name})
check("a second member joins the fixture (200)", joined.status_code == 200, joined.text)


def fixture_roles(role):
    return [str(uid) for uid in project(fixture_id)["roles"].get(role, [])]


response = assign_role(fixture_id, owner_id, other_id, "Product Owner")
check("Product Owner can be assigned (200)", response.status_code == 200, response.text)
check("the Product Owner holds it alone", fixture_roles("Product Owner") == [str(other_id)],
      fixture_roles("Product Owner"))

response = assign_role(fixture_id, owner_id, owner_id, "Product Owner")
check("a second Product Owner is refused (422)", response.status_code == 422, response.text)
check("the refusal explains the rule",
      "one member" in str(response.json().get("detail", "")).lower(), response.text)
check("the existing Product Owner is untouched", fixture_roles("Product Owner") == [str(other_id)],
      fixture_roles("Product Owner"))

response = assign_role(fixture_id, owner_id, other_id, "Product Owner")
check("re-assigning to the sitting holder stays a no-op (200)",
      response.status_code == 200, response.text)
check("still exactly one Product Owner", fixture_roles("Product Owner") == [str(other_id)],
      fixture_roles("Product Owner"))

response = assign_role(fixture_id, owner_id, other_id, "Scrum Master")
check("Scrum Master can be assigned (200)", response.status_code == 200, response.text)
response = assign_role(fixture_id, owner_id, owner_id, "Scrum Master")
check("a second Scrum Master is refused (422)", response.status_code == 422, response.text)

response = assign_role(fixture_id, owner_id, other_id, "Project Creator")
check("a second Project Creator is refused (422)", response.status_code == 422, response.text)
check("the original Project Creator keeps the role",
      fixture_roles("Project Creator") == [str(owner_id)], fixture_roles("Project Creator"))

# Manager and Employee stay multi-seat, so a second holder is fine.
response = assign_role(fixture_id, owner_id, other_id, "Manager")
check("Manager can be assigned (200)", response.status_code == 200, response.text)
response = assign_role(fixture_id, owner_id, owner_id, "Manager")
check("two Managers are allowed (200)", response.status_code == 200, response.text)

# The Add Member list hides exactly the members the route above would refuse.
CLIENT_HELPERS = os.path.join(PROJECT_ROOT, "src", "backend", "utils",
                              "project_role_helpers.py")
with open(CLIENT_HELPERS, encoding="utf-8") as handle:
    client_helpers_src = handle.read()
client_singleton_text = client_helpers_src.split("SINGLETON_PRESET_ROLES = (", 1)[-1].split(")", 1)[0]
client_singletons = [name.strip().strip("\"'") for name in client_singleton_text.split(",") if name.strip()]
check("the client and the server agree on the single-seat roles",
      client_singletons == list(SERVER_SINGLETONS),
      f"client={client_singletons} server={list(SERVER_SINGLETONS)}")

ROLE_DETAILS = os.path.join(PROJECT_ROOT, "src", "backend", "views",
                            "project_role_details.py")
with open(ROLE_DETAILS, encoding="utf-8") as handle:
    role_details_src = handle.read()
check("the Add Member list drops members who rank at least as high",
      "highest_preset_rank(project_data, uid) >= target_rank" in role_details_src)
check("a filled single-seat post says who holds it",
      "already holds" in role_details_src)


# ---------------------------------------------------------------------------
# The client's import graph.
#
# PyScript hands the browser these modules under their bare names - auth.py,
# server_data.py and friends sit in these two folders and settings.json maps them
# to ./auth.py and ./server_data.py - so a view imports `auth`, not
# `utils.auth`, and an editor cannot follow that without being told where to
# look (pyrightconfig.json's extraPaths). These checks keep both sides honest.
# ---------------------------------------------------------------------------
CLIENT_BARE_NAMES = (
    "auth", "dialog", "constants", "server_data", "project_helpers",
    "project_role_helpers", "project_layout", "layout", "sidebar_state",
    "charts", "settings", "sprint_access",
)
CLIENT_SOURCES = set()
for import_root in (os.path.join(PROJECT_ROOT, "src", "backend"),
                    os.path.join(PROJECT_ROOT, "src", "backend", "utils")):
    for dirpath, _dirnames, filenames in os.walk(import_root):
        CLIENT_SOURCES.update(name[:-3] for name in filenames if name.endswith(".py"))

unresolved_imports = []
repeated_imports = []
for dirpath, _dirnames, filenames in os.walk(os.path.join(PROJECT_ROOT, "src", "backend")):
    for filename in sorted(filenames):
        if not filename.endswith(".py"):
            continue
        seen = set()
        with open(os.path.join(dirpath, filename), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                parts = line.strip().split()
                if len(parts) < 4 or parts[0] != "from" or parts[2] != "import":
                    continue
                name = parts[1]
                if name not in CLIENT_BARE_NAMES:
                    continue
                if name not in CLIENT_SOURCES:
                    unresolved_imports.append(f"{filename}:{number} -> {name}")
                if name in seen:
                    repeated_imports.append(f"{filename}:{number} -> {name}")
                seen.add(name)

check("every bare-name client import resolves to a module file",
      not unresolved_imports, f"unresolved: {unresolved_imports}")
check("no client module imports the same name twice",
      not repeated_imports, f"repeated: {repeated_imports}")

# A module that exists only in the browser (js, pyodide, pyscript) can never be
# resolved by an editor, so its import line carries '# type: ignore'. Without it
# every page module reports a warning that hides the real ones. The module name
# is compared exactly - a prefix test would match "import json".
BROWSER_ONLY_MODULES = {"js", "pyodide", "pyscript"}
browser_imports_without_ignore = []
for dirpath, _dirnames, filenames in os.walk(os.path.join(PROJECT_ROOT, "src", "backend")):
    for filename in sorted(filenames):
        if not filename.endswith(".py"):
            continue
        with open(os.path.join(dirpath, filename), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                parts = line.strip().split()
                if len(parts) < 2 or parts[0] not in ("import", "from"):
                    continue
                if parts[1].split(".")[0] not in BROWSER_ONLY_MODULES:
                    continue
                if "type: ignore" not in line:
                    browser_imports_without_ignore.append(f"{filename}:{number}: {line.strip()}")

check("every browser-only import is marked '# type: ignore'",
      not browser_imports_without_ignore,
      f"missing ignore: {browser_imports_without_ignore}")

# A password is an opaque string, not a name: the server stores whatever was
# typed, so a page that strips whitespace off a password field produces a value
# the account can never match. login.py did exactly that, which made
# " Password123 " a password that could be registered but never used - and three
# failed tries now lock the account. Only the trimming is refused; reading a
# password field with .value is what every page should do.
PASSWORD_STRIP = re.compile(r"""["'][^"']*password[^"']*["']\s*\]\.value\.strip\(\)""", re.I)
trimmed_passwords = []
for dirpath, _dirnames, filenames in os.walk(os.path.join(PROJECT_ROOT, "src", "backend")):
    for filename in sorted(filenames):
        if not filename.endswith(".py"):
            continue
        with open(os.path.join(dirpath, filename), encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                if PASSWORD_STRIP.search(line):
                    trimmed_passwords.append(f"{filename}:{number}: {line.strip()}")

check("no client module strips whitespace off a password",
      not trimmed_passwords, f"trimmed: {trimmed_passwords}")


# ---------------------------------------------------------------------------
# Names the client calls but never defines.
#
# A merged module can end up calling a helper that the merge dropped, and
# nothing else notices: the file still compiles, no test imports it, and the
# fault only appears when that line runs - sprint-page.py calling
# _render_stopwatch_ui(), a helper only main ever had, which made every task
# click raise NameError and look like a dead card. Nested definitions count as
# defined here, so this errs towards silence; anything it does report cannot
# resolve.
# ---------------------------------------------------------------------------
CLIENT_DEFINED_NAMES = set(dir(builtins))
unresolved_calls = {}
for dirpath, _dirnames, filenames in os.walk(os.path.join(PROJECT_ROOT, "src", "backend")):
    for filename in sorted(filenames):
        if not filename.endswith(".py"):
            continue
        with open(os.path.join(dirpath, filename), encoding="utf-8") as handle:
            try:
                module = ast.parse(handle.read())
            except SyntaxError:
                continue

        defined = set(CLIENT_DEFINED_NAMES)
        for node in ast.walk(module):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.alias):
                defined.add((node.asname or node.name).split(".")[0])
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.Global):
                defined.update(node.names)

        for node in ast.walk(module):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id not in defined:
                    unresolved_calls.setdefault(filename, []).append(
                        f"line {node.lineno}: {node.func.id}()"
                    )

check("every name the client calls is defined in its own module",
      not unresolved_calls, f"unresolved calls: {unresolved_calls}")


if __name__ == "__main__":
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
