import pytest


@pytest.mark.api
def test_create_project_endpoint(client, seed_factory):
    """Projects: creating a project makes the caller its Project Creator."""
    seed_factory(users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}])

    # The server assigns the project id; the body needs user_id, name, description.
    response = client.post(
        "/api/projects",
        json={"user_id": 1, "name": "Software Engineering Project", "description": "Test project"},
    )
    assert response.status_code == 201

    project = response.json()["project"]
    assert project["name"] == "Software Engineering Project"
    assert project["members"] == [1]
    assert project["roles"]["Project Creator"] == [1]

    # The new project can be read back by its creator.
    fetched = client.get(f"/api/projects/{project['project_id']}", params={"user_id": 1})
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "Software Engineering Project"


@pytest.mark.api
def test_create_project_unknown_user_returns_404(client, seed_factory):
    """Projects: an account that does not exist cannot create a project."""
    seed_factory(users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}])

    response = client.post(
        "/api/projects",
        json={"user_id": 999, "name": "Ghost project", "description": "x"},
    )
    assert response.status_code == 404


@pytest.mark.api
def test_create_project_missing_name_returns_422(client, seed_factory):
    """Projects: a payload without a name is rejected."""
    seed_factory(users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}])

    response = client.post("/api/projects", json={"user_id": 1, "description": "no name"})
    assert response.status_code == 422