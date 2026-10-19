import pytest
from server.dependencies import check_project_permission

@pytest.mark.unit
@pytest.mark.parametrize("role,permission,expected", [
    ("Scrum Master", "manage_sprints", True),
    ("Member", "delete_project", False),
    ("Viewer", "edit_task", False)
])
def test_dependencies_role_permissions(role, permission, expected):
    """Test role-based permission evaluation rules."""
    result = check_project_permission(role, permission)
    assert result == expected