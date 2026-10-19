import pytest

@pytest.mark.api
def test_member_removal_permissions(client, seed_factory):
    """Members: a Scrum Master (manage_members) can remove a lower-ranked Employee."""
    seed_factory(
        users=[
            {"user_id": 1, "username": "sm", "email": "sm@monash.edu"},
            {"user_id": 2, "username": "emp", "email": "emp@monash.edu"},
        ],
        projects=[{
            "project_id": 101,
            "id": 101,
            "name": "Project Alpha",
            "description": "Test project",
            "members": [1, 2],
            "roles": {
                "Scrum Master": [1],
                "Employee": [2],
            },
            "role_definitions": {
                "Scrum Master": {"permissions": ["manage_members"]},
                "Employee": {"permissions": []},
            },
        }],
    )
    
    response = client.post(
        "/api/projects/101/members/2/remove",
        json={"user_id": 1}
    )
    assert response.status_code in (200, 204)

@pytest.mark.api
def test_member_removal_denied_without_permission(client, seed_factory):
    """Members: an Employee (no manage_members) cannot remove anyone."""
    seed_factory(
        users=[
            {"user_id": 1, "username": "sm", "email": "sm@monash.edu"},
            {"user_id": 2, "username": "emp", "email": "emp@monash.edu"},
        ],
        projects=[{
            "project_id": 101,
            "id": 101,
            "name": "Project Alpha",
            "description": "Test project",
            "members": [1, 2],
            "roles": {
                "Scrum Master": [1],
                "Employee": [2],
            },
            "role_definitions": {
                "Scrum Master": {"permissions": ["manage_members"]},
                "Employee": {"permissions": []},
            },
        }],
    )
    
    response = client.post(
        "/api/projects/101/members/1/remove",
        json={"user_id": 2}
    )
    assert response.status_code in (403, 401, 422, 400)