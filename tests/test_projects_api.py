import pytest

@pytest.mark.api
def test_create_project_endpoint(client, seed_factory):
    """Test creating a new project via the API."""
    seed_factory(users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}])
    
    response = client.post(
        "/api/projects",
        json={"name": "Software Engineering Project", "description": "Test project"},
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (200, 201)