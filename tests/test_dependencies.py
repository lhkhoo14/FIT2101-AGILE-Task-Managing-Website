import pytest
from fastapi import HTTPException
from server.dependencies import verify_project_permission

@pytest.mark.unit
def test_dependencies_role_permissions():
    """Test role-based permission evaluation rules using role definitions."""
    project = {
        "members": [1],
        "roles": {"Scrum Master": [1]},
        "role_definitions": {
            "Scrum Master": {"permissions": ["manage_sprints", "edit_task"]}
        }
    }
    
    # Valid permission should pass and return the project
    result = verify_project_permission(project, user_id=1, required_permission="manage_sprints")
    assert result == project

    # Missing permission should raise HTTP 403
    with pytest.raises(HTTPException) as exc_info:
        verify_project_permission(project, user_id=1, required_permission="delete_project")
    assert exc_info.value.status_code == 403