"""Shared pytest fixtures for the API and unit tests.

How the test database works
---------------------------
The application (server/main.py and every module under server/routes) imports its
helpers with FLAT names (``from database_manager import db_manager``). This file
therefore imports the very same flat modules, so the tests and the routes share ONE
``db_manager`` object. Each test then gets its own temporary JSON database file.

The real database file (server/data/server_database.json) is never touched, and
PostgreSQL is never used: DATABASE_URL is removed before anything is imported.
"""
import os
import sys
from pathlib import Path

# DATABASE_URL must be gone BEFORE database_manager is imported, because the module
# reads it at import time.
os.environ.pop("DATABASE_URL", None)

ROOT_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = ROOT_DIR / "server"
for _path in (str(SERVER_DIR), str(ROOT_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest
from fastapi.testclient import TestClient

from server import database_manager            # flat import: the module the routes use
from server import mailer

# Tests written as `from server import database_manager` / `from server.database_manager
# import ...` must get the SAME module object, otherwise they would talk to a second,
# separate db_manager that the routes never see.
sys.modules.setdefault("server.database_manager", database_manager)

from main import app               # flat import, exactly how uvicorn loads it


# --------------------------------------------------------------------------- helpers
def _database_managers() -> list:
    """Every DatabaseManager object currently loaded, the shared one first.

    The routes should hold the same object as the tests, but a module imported under
    two different names would give them a second copy. In JSON mode a manager keeps
    nothing in memory (every read/write/update goes to its file), so pointing ALL of
    them at the same temporary file is enough to make them see identical data.
    """
    managers = [database_manager.db_manager]
    seen = {id(managers[0])}
    for module in list(sys.modules.values()):
        candidate = getattr(module, "db_manager", None) if module is not None else None
        if candidate is not None and id(candidate) not in seen \
                and type(candidate).__name__ == "DatabaseManager":
            seen.add(id(candidate))
            managers.append(candidate)
    return managers


def _empty_database(manager) -> dict:
    """The structure the application expects (projects is a dict keyed by id)."""
    return manager._default_structure()


def _numeric_ids(values) -> list:
    ids = []
    for value in values:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            pass
    return ids


def seed_database(manager, users=None, projects=None, sprints=None, tasks=None) -> dict:
    """Write realistic test data into the database in the shape the app reads.

    users     list of user dicts (user_id, username, email, ...)
    projects  list of project dicts; stored under str(project_id) as the app expects
    sprints   list of sprint dicts. Give each one a "project_id" and it is attached
              to that project's "sprints" list.
    tasks     list of task dicts. Give each one "project_id", "sprint_id" and
              optionally "column" (default "backlog") and it is placed on that
              sprint's kanban board.
    Anything that cannot be attached is kept in a top-level list (ignored by the app).
    """
    data = manager.read()

    for user in users or []:
        user = dict(user)
        user.setdefault("password", "")
        user.setdefault("projects", [])
        data["users"].append(user)

    for project in projects or []:
        project = dict(project)
        project_id = project.get("project_id", project.get("id"))
        if project_id is None:
            project_id = data.get("next_project_id", 1)
        project.setdefault("project_id", project_id)
        project.setdefault("members", [])
        project.setdefault("sprints", [])
        project.setdefault("backlog", [])
        data["projects"][str(project_id)] = project

    for sprint in sprints or []:
        sprint = dict(sprint)
        owner = data["projects"].get(str(sprint.pop("project_id", "")))
        sprint.setdefault("kanban_state", {
            "backlog": [], "active": [], "review": [], "completed": []
        })
        if owner is not None:
            owner.setdefault("sprints", []).append(sprint)
        else:
            data.setdefault("sprints", []).append(sprint)

    for task in tasks or []:
        task = dict(task)
        owner = data["projects"].get(str(task.pop("project_id", "")))
        sprint_id = str(task.pop("sprint_id", ""))
        column = task.pop("column", "backlog")
        target = None
        if owner is not None:
            target = next(
                (s for s in owner.get("sprints", []) if str(s.get("id")) == sprint_id),
                None,
            )
        if target is not None:
            target.setdefault("kanban_state", {}).setdefault(column, []).append(task)
        else:
            data.setdefault("tasks", []).append(task)

    # New ids created through the API must not collide with the seeded ones.
    data["next_user_id"] = max([data.get("next_user_id", 1)]
                               + [i + 1 for i in _numeric_ids(u.get("user_id") for u in data["users"])])
    data["next_project_id"] = max([data.get("next_project_id", 1)]
                                  + [i + 1 for i in _numeric_ids(data["projects"].keys())])

    manager.write(data)
    return data


# --------------------------------------------------------------------------- fixtures
@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    """Give every test its own empty temporary JSON database."""
    manager = database_manager.db_manager
    path = str(tmp_path / "test_database.json")
    for each in _database_managers():
        monkeypatch.setattr(each, "db_path", path)
        monkeypatch.setattr(each, "database_url", None)     # never PostgreSQL
    manager.write(_empty_database(manager))
    yield manager


@pytest.fixture(autouse=True)
def no_real_emails(monkeypatch):
    """Tests must never send mail. Sent messages are recorded in `outbox`."""
    outbox = []

    def fake_send(to_email, link):
        outbox.append({"to": to_email, "link": link})
        return False

    monkeypatch.setattr(mailer, "send_verification_email", fake_send)
    return outbox


@pytest.fixture
def outbox(no_real_emails):
    """The verification emails the application tried to send during the test."""
    return no_real_emails


@pytest.fixture
def db(isolated_database):
    """The database manager, for tests that need to inspect stored data."""
    return isolated_database


@pytest.fixture
def client():
    """A FastAPI TestClient for the real application."""
    return TestClient(app)


@pytest.fixture
def seed_factory(isolated_database):
    """Factory fixture: seed users/projects/sprints/tasks into the test database."""
    def _seed(users=None, projects=None, sprints=None, tasks=None):
        return seed_database(isolated_database, users, projects, sprints, tasks)
    return _seed