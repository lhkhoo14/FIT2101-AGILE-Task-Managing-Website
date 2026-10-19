import os
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

if "DATABASE_URL" in os.environ:
    del os.environ["DATABASE_URL"]

_temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
_temp_db.close()

from server import database_manager
database_manager.db_manager.db_path = _temp_db.name  # type: ignore[attr-defined]

@pytest.fixture(autouse=True)
def reset_database():
    """Reset the JSON database before each test to ensure independence."""
    mgr = database_manager.db_manager
    initial_data = {
        "users": [],
        "projects": [],
        "sprints": [],
        "tasks": [],
        "time_logs": [],
        "history": []
    }
    # Use the actual methods available on DatabaseManager (e.g., read/write)
    if hasattr(mgr, "write"):
        mgr.write(initial_data)  # type: ignore[attr-defined]
    elif hasattr(mgr, "save_db"):
        mgr.save_db()  # type: ignore[attr-defined]
    yield

@pytest.fixture
def client():
    """Provide a FastAPI TestClient instance."""
    from server.main import app
    return TestClient(app)

@pytest.fixture
def seed_factory():
    """Factory fixture to seed realistic test data into the database."""
    def _seed(users=None, projects=None, sprints=None, tasks=None):
        mgr = database_manager.db_manager
        data = mgr.read() if hasattr(mgr, "read") else {}  # type: ignore[attr-defined]
        if users:
            data.setdefault("users", []).extend(users)
        if projects:
            data.setdefault("projects", []).extend(projects)
        if sprints:
            data.setdefault("sprints", []).extend(sprints)
        if tasks:
            data.setdefault("tasks", []).extend(tasks)
        if hasattr(mgr, "write"):
            mgr.write(data)  # type: ignore[attr-defined]
        return data
    return _seed