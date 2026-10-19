import pytest
from server.logic.contribution_logic import compute_contributions

@pytest.mark.unit
def test_contribution_logic_empty_logs():
    """Test contribution statistics calculation with no time logs or sprints."""
    project = {"members": [1], "sprints": []}
    users = [{"user_id": 1, "username": "alice"}]
    
    stats = compute_contributions(project, users)
    assert stats["total_logged_seconds"] == 0
    assert len(stats["members"]) == 1
    assert stats["members"][0]["assigned"] == 0