import pytest

@pytest.mark.api
def test_task_assignment_project_member_check(client, seed_factory):
    """Test that assigning a task to a non-project member is rejected (US-19)."""
    seed_factory(
        users=[
            {"user_id": 1, "username": "alice", "email": "alice@monash.edu"},
            {"user_id": 99, "username": "outsider", "email": "out@monash.edu"}
        ],
        projects=[{
            "id": 101,
            "name": "Project Alpha",
            "members": [1],  # 99 is NOT a member
            "roles": {"Project Creator": [1]},
            "sprints": [{
                "id": "s1",
                "name": "Sprint 1",
                "start_date": "2026-11-01",
                "end_date": "2026-11-14",
                "kanban_state": {
                    "backlog": [{"id": 1, "title": "Task 1", "assignee_id": 99}],
                    "active": [], "review": [], "completed": []
                }
            }]
        }]
    )
    
    response = client.put(
        "/api/projects/101/sprints/s1/kanban",
        json={
            "backlog": [{"id": 1, "title": "Task 1", "assignee_id": 99}],
            "active": [], "review": [], "completed": []
        },
        headers={"X-User-Id": "1"}
    )
    assert response.status_code in (400, 422)