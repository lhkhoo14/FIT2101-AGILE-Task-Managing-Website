"""server/dependencies.py: membership, permission and single-seat role rules."""
import pytest
from fastapi import HTTPException

import dependencies as deps


def project():
    return {
        "members": [1, 2],
        "roles": {"Scrum Master": [1], "Employee": [2]},
        "role_definitions": {
            "Scrum Master": {"permissions": ["manage_members"]},
            "Employee": {"permissions": []},
        },
    }


@pytest.mark.unit
def test_permission_check_follows_the_role_definitions():
    p = project()
    assert deps.verify_project_permission(p, 1, "manage_members") is p
    with pytest.raises(HTTPException) as denied:
        deps.verify_project_permission(p, 2, "manage_members")
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as outsider:
        deps.verify_project_permission(p, 9, "manage_members")
    assert outsider.value.status_code == 403


@pytest.mark.unit
def test_missing_project_is_a_404():
    with pytest.raises(HTTPException) as missing:
        deps.verify_project_access(None, 1)
    assert missing.value.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize("role", deps.SINGLETON_PRESET_ROLES)
def test_single_seat_roles_refuse_a_second_holder(role):
    p = {"roles": {role: [1]}, "role_definitions": {}}
    deps.validate_role_assignment(p, 1, role)        # the current holder again: allowed
    with pytest.raises(HTTPException) as second:
        deps.validate_role_assignment(p, 2, role)
    assert second.value.status_code == 422


@pytest.mark.unit
def test_conflicting_roles_cannot_be_held_together():
    p = {
        "roles": {"Employee": [2]},
        "role_definitions": {"Manager": {"conflicting_roles": ["Employee"]}},
    }
    with pytest.raises(HTTPException) as conflict:
        deps.validate_role_assignment(p, 2, "Manager")
    assert conflict.value.status_code == 422