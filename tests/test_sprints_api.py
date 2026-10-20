import pytest
from datetime import date, timedelta

@pytest.mark.api
def test_create_sprint_endpoint_valid_dates(client, seed_factory):
    """Sprints: a sprint with valid dates is created successfully[cite: 6]."""
    seed_factory(
        users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}]
    )
    
    proj_res = client.post(
        "/api/projects",
        json={"user_id": 1, "name": "Project Alpha", "description": "Test project"},
        headers={"X-User-Id": "1"}
    )
    assert proj_res.status_code in (200, 201)
    proj_data = proj_res.json().get("project", proj_res.json())
    proj_id = proj_data.get("project_id") or proj_data.get("id")
    
    start = date.today() + timedelta(days=1)
    end = date.today() + timedelta(days=14)
    
    response = client.post(
        f"/api/projects/{proj_id}/sprints",
        json={
            "user_id": 1,
            "name": "Sprint 1",
            "details": "First sprint",
            "status": "active",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    )
    assert response.status_code in (200, 201)

@pytest.mark.api
def test_create_sprint_end_before_start_returns_422(client, seed_factory):
    """Sprints: creating a sprint where end date is before start date is rejected[cite: 6]."""
    seed_factory(
        users=[{"user_id": 1, "username": "alice", "email": "alice@monash.edu"}]
    )
    
    proj_res = client.post(
        "/api/projects",
        json={"user_id": 1, "name": "Project Alpha", "description": "Test project"},
        headers={"X-User-Id": "1"}
    )
    proj_data = proj_res.json().get("project", proj_res.json())
    proj_id = proj_data.get("project_id") or proj_data.get("id")
    
    start = date.today() + timedelta(days=14)
    end = date.today() + timedelta(days=1)
    
    response = client.post(
        f"/api/projects/{proj_id}/sprints",
        json={
            "user_id": 1,
            "name": "Invalid Sprint",
            "details": "Bad dates",
            "status": "active",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
    )
    assert response.status_code in (400, 422)