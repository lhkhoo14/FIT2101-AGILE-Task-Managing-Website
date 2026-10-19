import pytest
from server.logic.membership_logic import can_remove_member

@pytest.mark.unit
@pytest.mark.parametrize("remover_role,target_role,expected", [
    ("Scrum Master", "Member", True),
    ("Member", "Scrum Master", False),
    ("Member", "Member", False)
])
def test_membership_logic_removal_rules(remover_role, target_role, expected):
    """Test rank-based member removal permissions."""
    assert can_remove_member(remover_role, target_role) == expected