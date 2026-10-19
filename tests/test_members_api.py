import pytest

@pytest.mark.api
def test_member_removal_permissions(client, seed_factory):
    """Test that a Scrum Master can successfully remove a regular member."""
    seed_factory(
        users=[
            {"user_id": 1, "username": "sm", "email": "sm@monash.edu"},
            {"user_id": 2, "username": "emp", "email": "emp@monash.edu"}
        ],
        projects=[{
            "id": 101,
            "name": "Project Alpha",
            "members": [1, 2],
            "roles": {
                "Scrum Master": [1],
                "Employee": [2]
            },
            "role_definitions": {
                "Scrum Master": {"permissions": ["manage_members"]},
                "Employee": {"permissions": []}
            }
        }]
    )
    
    response = client.delete(
        "/api/projects/101/members/2",
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (200, 204)