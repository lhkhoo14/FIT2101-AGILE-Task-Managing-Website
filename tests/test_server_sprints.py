"""Sprint and kanban routes."""
from datetime import date, timedelta

import pytest

from api_helpers import add_member, board, create_backlog_item, create_project, create_sprint, register, team


def kanban_url(pid, sid):
    return f"/api/projects/{pid}/sprints/{sid}/kanban"


def save(client, pid, sid, user, state):
    return client.put(kanban_url(pid, sid), json={"user_id": user, "state": state})


@pytest.fixture
def world(client):
    alice, bob, carol, pid = team(client)
    sprint = create_sprint(client, pid, alice, members=[bob])
    return client, alice, bob, carol, pid, sprint["id"]


# ---- create / list --------------------------------------------------------
@pytest.mark.api
def test_create_sprint_adds_leadership_and_validates(client):
    alice, bob, carol, pid = team(client)
    sprint = create_sprint(client, pid, alice, members=[bob, bob], tags=["x"], priority="high")
    assert sprint["members"] == [bob, alice] and sprint["priority"] == "high"
    assert sprint["kanban_state"] == board()
    url = f"/api/projects/{pid}/sprints"
    base = {"user_id": alice, "name": "S", "details": "d", "status": "active"}
    today = date.today()
    past = {**base, "start_date": (today - timedelta(days=9)).isoformat(), "end_date": (today - timedelta(days=2)).isoformat()}
    assert client.post(url, json=past).status_code == 422
    assert client.post(url, json={**base, "start_date": "bad", "end_date": "bad"}).status_code == 422
    ok = {**base, "start_date": today.isoformat(), "end_date": today.isoformat()}
    assert client.post(url, json={**ok, "members": [carol]}).status_code == 422   # not a project member
    assert client.post(url, json={**ok, "members": ["x"]}).status_code == 422
    assert client.post(url, json={**ok, "user_id": carol}).status_code == 403
    assert client.post("/api/projects/999/sprints", json=ok).status_code == 404


@pytest.mark.api
def test_list_and_get_sprint(world):
    client, alice, bob, carol, pid, sid = world
    listed = client.get(f"/api/projects/{pid}/sprints", params={"user_id": bob}).json()
    assert [s["id"] for s in listed] == [sid]
    assert client.get(f"/api/projects/{pid}/sprints/{sid}", params={"user_id": bob}).json()["name"] == "Sprint 1"
    assert client.get(f"/api/projects/{pid}/sprints/999", params={"user_id": bob}).status_code == 404
    assert client.get(f"/api/projects/{pid}/sprints", params={"user_id": carol}).status_code == 403


@pytest.mark.api
def test_loading_repairs_leadership_and_auto_completes_overdue_sprints(world, db):
    client, alice, bob, _, pid, sid = world
    state = db.read()
    sprint = state["projects"][str(pid)]["sprints"][0]
    sprint["members"] = [bob]                                    # leadership missing
    sprint["start_date"] = (date.today() - timedelta(days=10)).isoformat()
    sprint["end_date"] = (date.today() - timedelta(days=3)).isoformat()
    db.write(state)
    loaded = client.get(f"/api/projects/{pid}/sprints", params={"user_id": bob}).json()[0]
    assert alice in loaded["members"] and loaded["status"] == "ended" and loaded["auto_completed"] is True


# ---- status ---------------------------------------------------------------
@pytest.mark.api
def test_update_sprint_status(world):
    client, alice, bob, _, pid, sid = world
    url = f"/api/projects/{pid}/sprints/{sid}/status"
    assert client.patch(url, json={"user_id": alice, "status": "paused"}).status_code == 422
    assert client.patch(f"/api/projects/{pid}/sprints/999/status", json={"user_id": alice, "status": "ended"}).status_code == 404
    ended = client.patch(url, json={"user_id": alice, "status": "ended"})
    assert ended.status_code == 200 and ended.json()["sprint"]["ended_at"] == date.today().isoformat()
    assert client.patch(url, json={"user_id": alice, "status": "active"}).status_code == 409


# ---- kanban ---------------------------------------------------------------
@pytest.mark.api
def test_kanban_round_trip_and_batch_views(world):
    client, alice, bob, _, pid, sid = world
    state = board(backlog=[{"id": "task-1", "title": "A"}], active=[{"id": "task-2", "title": "B", "assignee_id": bob}])
    assert save(client, pid, sid, bob, state).status_code == 200
    fetched = client.get(kanban_url(pid, sid), params={"user_id": bob}).json()
    assert [t["id"] for t in fetched["backlog"]] == ["task-1"]
    assert client.get(f"/api/projects/{pid}/kanban-states", params={"user_id": bob}).json()[sid]["active"][0]["id"] == "task-2"
    flat = client.get(f"/api/projects/{pid}/sprints/{sid}/backlog", params={"user_id": bob}).json()
    assert {(t["id"], t["status"]) for t in flat} == {("task-1", "backlog"), ("task-2", "active")}


@pytest.mark.api
def test_kanban_validation_errors(world):
    client, alice, bob, carol, pid, sid = world
    assert save(client, pid, sid, bob, board(active=[{"id": "t", "title": "T", "description": "d" * 1001}])).status_code == 422
    assert save(client, pid, sid, bob, board(active=[{"id": "t", "title": "T", "description": 5}])).status_code == 422
    assert save(client, pid, sid, bob, board(active=[{"id": "t", "title": "T", "start_date": "2000-01-01"}])).status_code == 422
    assert save(client, pid, sid, bob, board(active=[{"id": "t", "title": "T", "start_date": "2999-01-01", "end_date": "2998-01-01"}])).status_code == 422
    assert save(client, pid, sid, bob, board(active=[{"id": "t", "title": "T", "assignee_id": carol}])).status_code == 422
    assert save(client, pid, sid, bob, board(active=[{"id": "t", "title": "T", "assignee_id": "x"}])).status_code == 422
    unfinished = board(completed=[{"id": "t", "title": "T", "checklist": [{"text": "a", "done": False}]}])
    assert save(client, pid, sid, bob, unfinished).status_code == 422
    assert save(client, pid, 999, bob, board()).status_code == 404


@pytest.mark.api
def test_completion_gets_stamped_and_kept(world):
    client, alice, bob, _, pid, sid = world
    done = board(completed=[{"id": "t", "title": "T", "checklist": [{"text": "a", "done": True}]}])
    assert save(client, pid, sid, bob, done).status_code == 200
    stamped = client.get(kanban_url(pid, sid), params={"user_id": bob}).json()["completed"][0]["completed_at"]
    assert stamped == date.today().isoformat()
    assert save(client, pid, sid, bob, done).status_code == 200
    assert client.get(kanban_url(pid, sid), params={"user_id": bob}).json()["completed"][0]["completed_at"] == stamped


@pytest.mark.api
def test_dropping_tasks_from_a_board(world, db):
    client, alice, bob, _, pid, sid = world
    save(client, pid, sid, bob, board(active=[{"id": "t1", "title": "One"}], completed=[{"id": "t2", "title": "Two"}]))
    # A completed task can never be dropped.
    assert save(client, pid, sid, bob, board(active=[{"id": "t1", "title": "One"}])).status_code == 409
    # An unfinished one can, by someone with manage_tasks, and it is audited.
    kept = board(completed=[{"id": "t2", "title": "Two"}])
    assert save(client, pid, sid, bob, kept).status_code == 200
    history = db.read()["projects"][str(pid)]["history"]
    assert history[-1]["action"] == "deleted_task" and history[-1]["task_title"] == "One"

    # Remove manage_tasks from Employee: dropping a task is now forbidden.
    state = db.read()
    state["projects"][str(pid)]["role_definitions"]["Employee"]["permissions"] = ["edit_sprints"]
    state["projects"][str(pid)]["sprints"][0]["kanban_state"] = board(active=[{"id": "t3", "title": "Three"}])
    db.write(state)
    assert save(client, pid, sid, bob, board()).status_code == 403


@pytest.mark.api
def test_description_edits_need_sprint_membership(client, db):
    alice, bob, carol, pid = team(client)
    add_member(client, pid, alice, "carol")
    create_sprint(client, pid, alice, members=[bob])
    state = db.read()
    state["projects"][str(pid)]["sprints"][0]["kanban_state"] = board(active=[{"id": "t", "title": "T"}])
    db.write(state)
    edited = board(active=[{"id": "t", "title": "T", "description": "new"}])
    assert save(client, pid, "1", carol, edited).status_code == 403
    assert save(client, pid, "1", bob, edited).status_code == 200


@pytest.mark.api
def test_ended_sprint_is_read_only(world):
    client, alice, bob, _, pid, sid = world
    client.patch(f"/api/projects/{pid}/sprints/{sid}/status", json={"user_id": alice, "status": "ended"})
    assert save(client, pid, sid, bob, board()).status_code == 409
    item = create_backlog_item(client, pid, alice)
    moved = client.post(f"/api/projects/{pid}/sprints/{sid}/backlog", json={"user_id": alice, "backlog_id": item["id"]})
    assert moved.status_code == 409
    assert client.request("DELETE", f"/api/projects/{pid}/sprints/{sid}", json={"user_id": alice}).status_code == 409
    assert client.request("DELETE", f"/api/projects/{pid}/sprints/{sid}/tasks/x", json={"user_id": alice}).status_code == 409
    back = client.post(f"/api/projects/{pid}/sprints/{sid}/tasks/x/return-to-backlog", json={"user_id": alice})
    assert back.status_code == 409


# ---- backlog <-> sprint ---------------------------------------------------
@pytest.mark.api
def test_move_backlog_item_into_sprint_and_back(world):
    client, alice, bob, _, pid, sid = world
    item = create_backlog_item(client, pid, alice, "Build it", tags=["api"], description="desc")
    move = client.post(f"/api/projects/{pid}/sprints/{sid}/backlog", json={"user_id": alice, "backlog_id": item["id"]})
    assert move.status_code == 200
    card = client.get(kanban_url(pid, sid), params={"user_id": bob}).json()["backlog"][0]
    assert card["id"] == f"task-{item['id']}" and card["tags"] == ["api"] and card["description"] == "desc"
    assert client.get(f"/api/projects/{pid}/backlog", params={"user_id": alice}).json() == []
    assert client.post(f"/api/projects/{pid}/sprints/{sid}/backlog", json={"user_id": alice, "backlog_id": 999}).status_code == 404

    back = client.post(f"/api/projects/{pid}/sprints/{sid}/tasks/{card['id']}/return-to-backlog", json={"user_id": bob})
    assert back.status_code == 200 and back.json()["backlog_item"]["id"] == item["id"]
    assert [i["title"] for i in client.get(f"/api/projects/{pid}/backlog", params={"user_id": alice}).json()] == ["Build it"]


@pytest.mark.api
def test_return_to_backlog_guards(world, db):
    client, alice, bob, carol, pid, sid = world
    state = db.read()
    sprint = state["projects"][str(pid)]["sprints"][0]
    sprint["kanban_state"] = board(
        backlog=[{"id": "task-5", "title": "Timed", "time_log": {"started_at": "2026-01-01T00:00:00+00:00"}},
                 {"id": "free-text-id", "title": "Odd"}],
        active=[{"id": "task-6", "title": "Started"}])
    state["projects"][str(pid)]["backlog"] = [{"id": 7}]
    db.write(state)
    url = lambda t, u: client.post(f"/api/projects/{pid}/sprints/{sid}/tasks/{t}/return-to-backlog", json={"user_id": u})
    assert url("task-5", carol).status_code == 403                      # not on the project
    assert url("task-5", bob).status_code == 409                        # has logged work
    assert url("task-6", bob).status_code == 409                        # already started
    assert url("task-404", bob).status_code == 404
    odd = url("free-text-id", bob)
    assert odd.status_code == 200 and odd.json()["backlog_item"]["id"] >= 8     # gets a fresh id
    sprint_members_only = client.post(f"/api/projects/{pid}/sprints/{sid}/tasks/x/return-to-backlog", json={"user_id": alice})
    assert sprint_members_only.status_code in (404, 409)


@pytest.mark.api
def test_return_requires_sprint_membership(client):
    alice, bob, carol, pid = team(client)
    add_member(client, pid, alice, "carol")
    create_sprint(client, pid, alice, members=[bob])
    assert client.post(f"/api/projects/{pid}/sprints/1/tasks/x/return-to-backlog", json={"user_id": carol}).status_code == 403


# ---- deleting -------------------------------------------------------------
@pytest.mark.api
def test_delete_task(world, db):
    client, alice, bob, carol, pid, sid = world
    save(client, pid, sid, bob, board(active=[{"id": "task-1", "title": "Doomed"}], completed=[{"id": "task-2", "title": "Done"}]))
    url = lambda t: f"/api/projects/{pid}/sprints/{sid}/tasks/{t}"
    assert client.request("DELETE", url("task-1"), json={"user_id": carol}).status_code == 403
    assert client.request("DELETE", url("task-9"), json={"user_id": bob}).status_code == 404
    assert client.request("DELETE", url("task-2"), json={"user_id": bob}).status_code == 409
    assert client.request("DELETE", f"/api/projects/{pid}/sprints/999/tasks/x", json={"user_id": bob}).status_code == 404
    ok = client.request("DELETE", url("1"), json={"user_id": bob})
    assert ok.status_code == 200 and "Doomed" in ok.json()["message"]
    assert db.read()["projects"][str(pid)]["history"][-1]["action"] == "deleted_task"
    state = db.read()
    state["projects"][str(pid)]["role_definitions"]["Employee"]["permissions"] = []
    db.write(state)
    assert client.request("DELETE", url("task-2"), json={"user_id": bob}).status_code == 403


@pytest.mark.api
def test_delete_sprint(world, db):
    client, alice, bob, carol, pid, sid = world
    url = f"/api/projects/{pid}/sprints/{sid}"
    assert client.request("DELETE", url, json={"user_id": bob}).status_code == 403          # Employee lacks manage_sprints
    assert client.request("DELETE", f"/api/projects/{pid}/sprints/999", json={"user_id": alice}).status_code == 404
    ok = client.request("DELETE", url, json={"user_id": alice})
    assert ok.status_code == 200 and ok.json()["sprint_id"] == sid
    assert client.get(f"/api/projects/{pid}/sprints", params={"user_id": alice}).json() == []
    assert db.read()["projects"][str(pid)]["history"][-1]["action"] == "deleted_sprint"