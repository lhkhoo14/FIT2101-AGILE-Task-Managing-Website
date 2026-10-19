import pytest

@pytest.mark.api
def test_create_sprint_endpoint_valid_dates(client, seed_factory):
    """Test creating a sprint with valid start and end dates."""
    seed_factory(
        users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}],
        projects=[{
            "id": 101,  # Use 'id'
            "name": "Project Alpha",
            "members": [1],
            "roles": {"Project Creator": [1]}
        }]
    )
    
    response = client.post(
        "/api/projects/101/sprints",
        json={"name": "Sprint 1", "start_date": "2026-11-01", "end_date": "2026-11-14"},
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (200, 201)

@pytest.mark.api
def test_create_sprint_endpoint_invalid_dates(client, seed_factory):
    """Test creating a sprint where end date is before start date fails."""
    seed_factory(
        users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}],
        projects=[{
            "id": 101,  # Use 'id'
            "name": "Project Alpha",
            "members": [1],
            "roles": {"Project Creator": [1]}
        }]
    )
    
    response = client.post(
        "/api/projects/101/sprints",
        json={"name": "Sprint Bad", "start_date": "2026-11-14", "end_date": "2026-11-01"},
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (400, 422)