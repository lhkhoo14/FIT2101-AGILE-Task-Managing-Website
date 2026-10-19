import os
import tempfile
import pytest
from fastapi.testclient import TestClient

# Safety rule 4: Remove DATABASE_URL before importing server
if "DATABASE_URL" in os.environ:
    del os.environ["DATABASE_URL"]

# Create a temporary database file for testing
_temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
_temp_db.close()

from server import database_manager
database_manager.db_manager.db_path = _temp_db.name

@pytest.fixture(autouse=True)
def reset_database():
    """Reset the JSON database before each test to ensure independence."""
    database_manager.db_manager.data = {
        "users": [],
        "projects": [],
        "sprints": [],
        "tasks": [],
        "time_logs": [],
        "history": []
    }
    database_manager.db_manager.save_db()
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
        data = database_manager.db_manager.load_db()
        if users:
            data["users"].extend(users)
        if projects:
            data["projects"].extend(projects)
        if sprints:
            data["sprints"].extend(sprints)
        if tasks:
            data["tasks"].extend(tasks)
        database_manager.db_manager.save_db()
        return data
    return _seed