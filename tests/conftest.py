"""Shared fixtures: an isolated JSON database and a FastAPI TestClient.

The server imports itself two ways: the app and its routes use bare module names
(`from database_manager import db_manager`, because uvicorn runs from server/),
while the tests import the same files as `server.database_manager`. Python treats
those as two separate modules with two separate `db_manager` objects. Pointing
only one of them at the temporary file would leave the app reading the real
server/data/server_database.json, so both are redirected here.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "server"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

# A developer's DATABASE_URL must never be used by the tests.
os.environ.pop("DATABASE_URL", None)

_temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
_temp_db.close()

import database_manager as _app_database          # type: ignore # the module the routes use
from server import database_manager as _pkg_database  # the module the tests import

for _manager in (_app_database.db_manager, _pkg_database.db_manager):
    _manager.db_path = _temp_db.name
    _manager.database_url = None


def empty_database():
    return {
        "next_user_id": 1,
        "next_project_id": 1,
        "next_backlog_id": 1,
        "next_sprint_id": 1,
        "users": [],
        "projects": {},
    }


@pytest.fixture(autouse=True)
def reset_database():
    """Start every test from an empty database so tests cannot affect each other."""
    _app_database.db_manager.write(empty_database())
    yield


@pytest.fixture
def db():
    """The live database manager, for reading back what an endpoint stored."""
    return _app_database.db_manager


@pytest.fixture
def client():
    from server.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def seed_factory():
    """Insert hand-written records. `projects` may be a list; it is stored the way
    the server stores it: a dict keyed by the project id as a string."""
    def _seed(users=None, projects=None, sprints=None, tasks=None):
        manager = _app_database.db_manager
        data = manager.read()
        if users:
            data["users"].extend(users)
            data["next_user_id"] = max(
                [data.get("next_user_id", 1)] + [u["user_id"] + 1 for u in users]
            )
        for project in projects or []:
            key = str(project.get("project_id", project.get("id")))
            project.setdefault("project_id", project.get("id"))
            data["projects"][key] = project
        manager.write(data)
        return data
    return _seed