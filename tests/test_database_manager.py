import pytest
from server.database_manager import DatabaseManager

@pytest.mark.unit
def test_database_manager_persistence(tmp_path):
    """Test saving and loading data through the database manager."""
    db_file = tmp_path / "test_db.json"
    manager = DatabaseManager(db_path=str(db_file))
    
    # Set initial test data and write using the manager's write method
    test_data = {"users": [{"id": 1, "username": "alice"}], "projects": []}
    if hasattr(manager, "write"):
        manager.write(test_data)  # type: ignore[attr-defined]
    
    # Reload/read from disk
    loaded = manager.read() if hasattr(manager, "read") else {}  # type: ignore[attr-defined]
    assert len(loaded["users"]) == 1
    assert loaded["users"][0]["username"] == "alice"