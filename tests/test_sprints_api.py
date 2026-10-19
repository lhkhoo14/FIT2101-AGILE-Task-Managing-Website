import pytest
from datetime import date, timedelta

@pytest.mark.api
def test_create_sprint_endpoint_valid_dates(client, seed_factory):
    """Sprints: a sprint with valid dates is created successfully."""
    seed_factory(
        users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}],
        projects=[{
            "project_id": 101,
            "id": 101,
            "name": "Project Alpha",
            "members": [1],
            "roles": {"Project Creator": [1]},
        }],
    )
    
    start = date.today() + timedelta(days=1)
    end = date.today() + timedelta(days=14)
    
    response = client.post(
        "/api/projects/101/sprints",
        json={
            "sprint_id": "s1",
            "name": "Sprint 1",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (200, 201)

@pytest.mark.api
def test_create_sprint_end_before_start_returns_422(client, seed_factory):
    """Sprints: creating a sprint where end date is before start date is rejected."""
    seed_factory(
        users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}],
        projects=[{
            "project_id": 101,
            "id": 101,
            "name": "Project Alpha",
            "members": [1],
            "roles": {"Project Creator": [1]},
        }],
    )
    
    start = date.today() + timedelta(days=14)
    end = date.today() + timedelta(days=1)
    
    response = client.post(
        "/api/projects/101/sprints",
        json={
            "sprint_id": "s2",
            "name": "Invalid Sprint",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (400, 422)