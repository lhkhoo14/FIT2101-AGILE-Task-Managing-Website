"""Change history, contributions and time-log routes."""
import pytest

from api_helpers import add_member, board, create_sprint, register, team


@pytest.fixture
def world(client, db):
    alice, bob, carol, pid = team(client)
    create_sprint(client, pid, alice, members=[bob])
    state = db.read()
    state["projects"][str(pid)]["sprints"][0]["kanban_state"] = board(
        active=[{"id": "task-1", "title": "Build", "assignee_id": bob}],
        completed=[{"id": "task-2", "title": "Ship", "assignee": "bob"}])
    db.write(state)
    return client, alice, bob, carol, pid


def log_url(pid, task="task-1", sprint="1"):
    return f"/api/projects/{pid}/sprints/{sprint}/tasks/{task}/time-log"


# ---- history --------------------------------------------------------------
@pytest.mark.api
def test_history_add_list_and_limits(world):
    client, alice, bob, carol, pid = world
    url = f"/api/projects/{pid}/history"
    first = client.post(url, json={"user_id": alice, "message": "one"})
    assert first.status_code == 201 and first.json()["actor"] == "alice" and first.json()["id"] == 1
    client.post(url, json={"user_id": bob, "message": "two", "action": "x", "timestamp": "2020-01-01 00:00 UTC"})
    listed = client.get(url, params={"user_id": alice}).json()
    assert [e["message"] for e in listed] == ["two", "one"]               # newest first
    assert listed[0]["timestamp"] == "2020-01-01 00:00 UTC"
    assert len(client.get(url, params={"user_id": alice, "limit": 1}).json()) == 1
    assert len(client.get(url, params={"user_id": alice, "limit": 0}).json()) == 1   # clamped to at least 1
    assert client.get(url, params={"user_id": carol}).status_code == 403
    assert client.post(url, json={"user_id": carol, "message": "x"}).status_code == 403
    assert client.post("/api/projects/999/history", json={"user_id": alice, "message": "x"}).status_code == 404


@pytest.mark.api
def test_history_user_must_exist(client, seed_factory):
    seed_factory(projects=[{"project_id": 1, "members": [42]}])
    assert client.post("/api/projects/1/history", json={"user_id": 42, "message": "m"}).status_code == 404


@pytest.mark.api
def test_history_is_capped(world, db):
    from logic.contribution_logic import HISTORY_LIMIT
    client, alice, _, _, pid = world
    state = db.read()
    state["projects"][str(pid)]["history"] = [{"id": i, "message": str(i)} for i in range(1, HISTORY_LIMIT + 1)]
    db.write(state)
    client.post(f"/api/projects/{pid}/history", json={"user_id": alice, "message": "newest"})
    stored = db.read()["projects"][str(pid)]["history"]
    assert len(stored) == HISTORY_LIMIT and stored[-1]["message"] == "newest" and stored[0]["id"] == 2


# ---- contributions --------------------------------------------------------
@pytest.mark.api
def test_contributions_counts_assigned_and_completed(world):
    client, alice, bob, carol, pid = world
    stats = client.get(f"/api/projects/{pid}/contributions", params={"user_id": alice}).json()
    by_name = {m["name"]: m for m in stats["members"]}
    assert by_name["bob"]["assigned"] == 2 and by_name["bob"]["completed"] == 1
    assert by_name["alice"]["assigned"] == 0
    assert client.get(f"/api/projects/{pid}/contributions", params={"user_id": carol}).status_code == 403


# ---- time log -------------------------------------------------------------
@pytest.mark.api
def test_start_and_stop_a_work_session(world, db):
    client, alice, bob, _, pid = world
    started = client.post(log_url(pid), json={"user_id": bob, "action": "START"})
    assert started.status_code == 200 and started.json()["work_log"]["ended_at"] is None
    again = client.post(log_url(pid), json={"user_id": bob, "action": "start"})      # idempotent
    assert again.json()["work_log"]["started_at"] == started.json()["work_log"]["started_at"]
    stopped = client.post(log_url(pid), json={"user_id": bob, "action": "stop"})
    assert stopped.status_code == 200 and stopped.json()["work_log"]["ended_at"]
    assert stopped.json()["task_seconds"] >= 0
    actions = [e["action"] for e in db.read()["projects"][str(pid)]["history"]]
    assert actions.count("time_log") == 3
    members = {m["name"]: m for m in stopped.json()["contributions"]["members"]}
    assert len(members["bob"]["work_logs"]) == 1


@pytest.mark.api
def test_time_log_rejections(world, db):
    client, alice, bob, carol, pid = world
    assert client.post(log_url(pid), json={"user_id": bob, "action": "pause"}).status_code == 422
    assert client.post(log_url(pid), json={"user_id": bob, "action": "stop"}).status_code == 409        # nothing running
    assert client.post(log_url(pid, task="nope"), json={"user_id": bob, "action": "start"}).status_code == 404
    assert client.post(log_url(pid, sprint="99"), json={"user_id": bob, "action": "start"}).status_code == 404
    assert client.post(log_url(pid), json={"user_id": carol, "action": "start"}).status_code == 403     # not on the project
    add_member(client, pid, alice, "carol")
    assert client.post(log_url(pid), json={"user_id": carol, "action": "start"}).status_code == 403     # not on the sprint
    assert client.post("/api/projects/999/sprints/1/tasks/t/time-log", json={"user_id": alice, "action": "start"}).status_code == 404
    client.patch(f"/api/projects/{pid}/sprints/1/status", json={"user_id": alice, "status": "ended"})
    assert client.post(log_url(pid), json={"user_id": bob, "action": "start"}).status_code == 409


@pytest.mark.api
def test_overdue_sprint_is_settled_before_logging(world, db):
    from datetime import date, timedelta
    client, _, bob, _, pid = world
    state = db.read()
    sprint = state["projects"][str(pid)]["sprints"][0]
    sprint["start_date"] = (date.today() - timedelta(days=9)).isoformat()
    sprint["end_date"] = (date.today() - timedelta(days=2)).isoformat()
    db.write(state)
    assert client.post(log_url(pid), json={"user_id": bob, "action": "start"}).status_code == 409