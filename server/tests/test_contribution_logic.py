import pytest
from server.logic.contribution_logic import calculate_user_contributions

@pytest.mark.unit
def test_contribution_logic_empty_logs():
    """Test contribution statistics calculation with no time logs."""
    stats = calculate_user_contributions([], user_id=1)
    assert stats["total_hours"] == 0.0
    assert stats["task_count"] == 0