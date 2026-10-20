import pytest


def _seed_project(seed_factory):
    seed_factory(
        users=[
            {"user_id": 1, "username": "sm", "email": "sm@monash.edu"},
            {"user_id": 2, "username": "emp", "email": "emp@monash.edu"},
        ],
        projects=[{
            "project_id": "101",
            "id": "101",
            "name": "Project Alpha",
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


@pytest.mark.api
def test_member_removal_permissions(client, seed_factory):
    """Members: a Scrum Master (manage_members) can remove a lower-ranked Employee."""
    _seed_project(seed_factory)

    # The acting user goes in the JSON body, and removal is a POST to /remove.
    response = client.post("/api/projects/101/members/2/remove", json={"user_id": 1})
    assert response.status_code == 200, response.text
    assert response.json()["member_id"] == 2

    # The member is really gone from the project.
    members = client.get("/api/projects/101/members", params={"user_id": 1}).json()
    assert 2 not in members["members"]
    assert 1 in members["members"]


@pytest.mark.api
def test_member_removal_denied_without_permission(client, seed_factory):
    """Members: an Employee (no manage_members) cannot remove anyone."""
    _seed_project(seed_factory)

    response = client.post("/api/projects/101/members/1/remove", json={"user_id": 2})
    assert response.status_code == 403, response.text