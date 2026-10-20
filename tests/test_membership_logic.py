import pytest
from server.logic.membership_logic import can_remove_member

@pytest.mark.unit
def test_membership_logic_removal():
    """Test rank-based member removal permissions using real project structures."""
    project = {
        "members": [1, 2],
        "roles": {
            "Project Creator": [1],
            "Employee": [2]
        },
        "role_definitions": {}
    }
    # Project Creator (1) can remove Employee (2)
    assert can_remove_member(project, actor_id=1, target_id=2) is True
    # Employee (2) cannot remove Project Creator (1)
    assert can_remove_member(project, actor_id=2, target_id=1) is False