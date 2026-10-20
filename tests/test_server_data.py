"""Unit tests for the browser-side API client (src/backend/server_data.py).

pyfetch is replaced by a recorder, so no server is needed. Every method is run
through the same four situations: success, a server error, a network failure,
and (where the method needs a login) no active session.
"""
import asyncio

import pytest

import frontend_stubs

fetch, window = frontend_stubs.install()
import server_data  # noqa: E402
from server_data import ServerData, Project  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean():
    fetch.calls.clear()
    fetch.reply(200, {})
    window.localStorage.data.clear()
    yield


@pytest.fixture
def db():
    client = ServerData()
    client.set_active_session(7)
    return client


# ---- session handling ----------------------------------------------------
@pytest.mark.unit
def test_session_is_stored_loaded_and_cleared():
    client = ServerData()
    assert client.get_active_session() is None
    client.set_active_session(42)
    assert client.get_active_session() == 42
    assert window.localStorage.getItem(client.session_key) == "42"

    assert ServerData().get_active_session() == 42       # a new client reads it back
    client.clear_session()
    assert client.get_active_session() is None
    assert ServerData().get_active_session() is None


@pytest.mark.unit
def test_load_session_ignores_garbage():
    window.localStorage.setItem(ServerData().session_key, "not-a-number")
    assert ServerData().get_active_session() is None


@pytest.mark.unit
def test_project_model_defaults():
    project = Project(1, "n", "d", "active")
    assert project.created_at is None and project.permissions == set()
    assert Project(1, "n", "d", "active", 5, {"x"}).permissions == {"x"}


# ---- table of every HTTP-backed method -----------------------------------
# kind: "tuple" -> (ok, ...) ; "list" -> [] on failure ; "dict" -> {} on failure ;
#       "none" -> None on failure
# needs_session: whether the method refuses to run without a logged-in user.
# ok: the status that means success. payload: what the server returns on success.
CASES = [
    # name, args, kind, http method, url fragment, ok status, payload, needs_session
    ("register_user", ("bob", "b@x.com", "pw"), "tuple", "POST", "/register", 201, {}, False),
    ("validate_login", ("b@x.com", "pw"), "tuple", "POST", "/login", 200, {"user_id": 3}, False),
    ("get_user_by_id", (3,), "none", "GET", "/users/3", 200, {"user_id": 3}, False),
    ("get_users", (), "list", "GET", "/users?user_id=7", 200, [{"user_id": 1}], True),
    ("create_project", ("P", "desc"), "tuple", "POST", "/projects", 201, {"project": {"project_id": 9}}, True),
    ("get_projects", (), "none", "GET", "/users/7/projects", 200,
     [{"project_id": 1, "name": "A", "description": "d", "status": "active", "created_at": 5, "roles": {}}], True),
    ("get_project_by_id", (1,), "none", "GET", "/projects/1?user_id=7", 200,
     {"project_id": 1, "name": "A", "description": "d", "status": None}, True),
    ("update_project_status", (1, "completed"), "tuple", "PATCH", "/projects/1/status", 200, {}, True),
    ("get_project_members", (1,), "none", "GET", "/projects/1/members?user_id=7", 200, {"members": [1]}, True),
    ("add_project_member", (1, "bob"), "tuple", "POST", "/projects/1/members", 200, {}, True),
    ("get_backlog_items", (1,), "list", "GET", "/projects/1/backlog?user_id=7", 200, [{"id": 1}], True),
    ("create_backlog_item", (1, "T", ["a"], "high", "desc"), "tuple", "POST", "/projects/1/backlog", 201, {"id": 5}, True),
    ("get_sprints", (1,), "list", "GET", "/projects/1/sprints?user_id=7", 200, [{"id": 1}], True),
    ("create_sprint", (1, "S", "d", "active", "2026-10-01", "2026-10-14"), "tuple", "POST",
     "/projects/1/sprints", 201, {"id": 2}, True),
    ("get_sprint_backlog", (1, 2), "list", "GET", "/projects/1/sprints/2/backlog?user_id=7", 200, [{"id": 1}], True),
    ("get_kanban_state", (1, 2), "none", "GET", "/projects/1/sprints/2/kanban?user_id=7", 200, {"backlog": []}, True),
    ("get_project_kanban_states", (1,), "dict", "GET", "/projects/1/kanban-states?user_id=7", 200, {"2": {}}, True),
    ("move_backlog_item_to_sprint", (1, 5, 2), "tuple", "POST", "/projects/1/sprints/2/backlog", 201, {}, True),
    ("return_task_to_backlog", (1, 2, 5), "tuple", "POST",
     "/projects/1/sprints/2/tasks/5/return-to-backlog", 200, {"backlog_item": {"id": 5}}, True),
    ("update_kanban_state", (1, 2, {"backlog": []}), "tuple", "PUT", "/projects/1/sprints/2/kanban", 200, {}, True),
    ("update_sprint_status", (1, 2, "ended"), "tuple", "PATCH", "/projects/1/sprints/2/status", 200,
     {"sprint": {"id": 2}}, True),
    ("get_account_settings", (), "tuple", "GET", "/users/7/settings", 200, {"username": "u"}, True),
    ("update_profile", ("new", "img"), "tuple", "PATCH", "/users/7/profile", 200, {"username": "new"}, True),
    ("request_email_change", ("n@x.com",), "tuple", "POST", "/users/7/email-change", 200, {}, True),
    ("verify_email_change", ("tok",), "tuple", "POST", "/users/email-verify", 200, {}, False),
    ("change_password", ("old", "new"), "tuple", "POST", "/users/7/password", 200, {}, True),
    ("get_change_history", (1,), "list", "GET", "/projects/1/history?user_id=7", 200, [{"message": "m"}], True),
    ("record_change", (1, "did a thing"), "tuple", "POST", "/projects/1/history", 201, {}, True),
    ("get_contributions", (1,), "dict", "GET", "/projects/1/contributions?user_id=7", 200, {"members": []}, True),
    ("log_task_time", (1, 2, 5, "start"), "tuple", "POST", "/projects/1/sprints/2/tasks/5/time-log", 200,
     {"task": {}}, True),
    ("create_project_role", (1, "QA", "#fff", "d", ["review_tasks"], []), "tuple", "POST", "/projects/1/roles", 201, {}, True),
    ("delete_project_role", (1, "QA"), "tuple", "DELETE", "/projects/1/roles/QA", 200, {}, True),
    ("update_project_role", (1, "QA", "#fff", "d", ["x"], []), "tuple", "PUT", "/projects/1/roles/QA", 200, {}, True),
    ("get_role_members", (1, "QA"), "list", "GET", "/projects/1/roles/QA/members?user_id=7", 200, {"members": [1]}, True),
    ("remove_role_member", (1, "QA", 3), "tuple", "POST", "/projects/1/roles/QA/remove", 200, {}, True),
    ("assign_project_role", (1, "QA", 3), "tuple", "POST", "/projects/1/roles/assign", 200, {}, True),
    ("get_all_users", (), "list", "GET", "/users?user_id=7", 200, [{"user_id": 1}], True),
    ("delete_project", (1,), "tuple", "DELETE", "/projects/1", 200, {"message": "gone"}, True),
    ("delete_sprint", (1, 2), "tuple", "DELETE", "/projects/1/sprints/2", 200, {"message": "gone"}, True),
    ("delete_task", (1, 2, "t 1"), "tuple", "DELETE", "/projects/1/sprints/2/tasks/t%201", 200, {"message": "gone"}, True),
    ("remove_project_member", (1, 3), "tuple", "POST", "/projects/1/members/3/remove", 200, {"message": "gone"}, True),
    ("delete_account", ("pw",), "tuple", "POST", "/users/7/delete", 200, {"message": "gone"}, True),
]
IDS = [case[0] for case in CASES]


def call(db, name, args):
    return run(getattr(db, name)(*args))


def is_failure(result, kind):
    if kind == "tuple":
        return result[0] is False
    if kind == "list":
        return result == []
    if kind == "dict":
        return result == {}
    return result is None


@pytest.mark.unit
@pytest.mark.parametrize("name,args,kind,method,url,ok,payload,needs", CASES, ids=IDS)
def test_success_sends_the_right_request(db, name, args, kind, method, url, ok, payload, needs):
    fetch.reply(ok, payload)
    result = call(db, name, args)

    assert fetch.calls, "the method never contacted the server"
    sent_url, kwargs = fetch.calls[0]
    assert url in sent_url
    assert sent_url.startswith(db.api_url)
    assert kwargs.get("method", "GET") == method
    assert not is_failure(result, kind) or kind == "list" and payload == []


@pytest.mark.unit
@pytest.mark.parametrize("name,args,kind,method,url,ok,payload,needs", CASES, ids=IDS)
def test_server_error_is_reported_as_failure(db, name, args, kind, method, url, ok, payload, needs):
    fetch.reply(500, {"detail": "boom"})
    assert is_failure(call(db, name, args), kind)


@pytest.mark.unit
@pytest.mark.parametrize("name,args,kind,method,url,ok,payload,needs", CASES, ids=IDS)
def test_network_failure_never_raises(db, name, args, kind, method, url, ok, payload, needs):
    fetch.fail()
    assert is_failure(call(db, name, args), kind)


@pytest.mark.unit
@pytest.mark.parametrize("name,args,kind,method,url,ok,payload,needs",
                         [c for c in CASES if c[7]], ids=[c[0] for c in CASES if c[7]])
def test_methods_that_need_a_login_refuse_without_one(name, args, kind, method, url, ok, payload, needs):
    client = ServerData()          # fixture cleared storage: nobody is logged in
    fetch.reply(ok, payload)
    result = call(client, name, args)
    assert is_failure(result, kind)
    assert fetch.calls == [], "no request may be sent without a session"


# ---- behaviours worth pinning individually -------------------------------
@pytest.mark.unit
def test_login_success_stores_the_session():
    client = ServerData()
    fetch.reply(200, {"user_id": 12})
    assert run(client.validate_login("a@x.com", "pw")) == (True, "")
    assert client.get_active_session() == 12


@pytest.mark.unit
def test_login_failure_formats_validation_error_lists():
    client = ServerData()
    fetch.reply(422, {"detail": [{"msg": "bad email"}, {"msg": "short password"}]})
    ok, message = run(client.validate_login("x", "y"))
    assert ok is False and message == "bad email; short password"
    assert client.get_active_session() is None


@pytest.mark.unit
def test_login_failure_shows_server_message():
    fetch.reply(401, {"detail": "Invalid credentials"})
    assert run(ServerData().validate_login("a", "b")) == (False, "Invalid credentials")


@pytest.mark.unit
def test_register_reports_server_message_and_connection_error():
    client = ServerData()
    fetch.reply(409, {"detail": "Email already registered"})
    assert run(client.register_user("a", "b", "c")) == (False, "Email already registered")
    fetch.fail()
    assert run(client.register_user("a", "b", "c")) == (False, "Unable to connect to the server.")


@pytest.mark.unit
def test_get_projects_builds_project_objects(db):
    fetch.reply(200, [
        {"project_id": 1, "name": "A", "description": "d", "status": "completed", "created_at": 99,
         "roles": {"Scrum Master": [7]},
         "role_definitions": {"Scrum Master": {"permissions": ["manage_sprints"]}}},
        {"id": 2},
    ])
    projects = run(db.get_projects())
    assert [p.id for p in projects] == [1, 2]
    assert projects[0].status == "completed" and projects[0].created_at == 99
    assert projects[0].permissions == {"manage_sprints"}
    assert projects[1].name == "Untitled Project" and projects[1].status == "active"
    assert projects[1].created_at is None


@pytest.mark.unit
def test_get_project_by_id_defaults_and_denied(db):
    fetch.reply(200, {"project_id": 4, "name": "N", "status": None})
    project = run(db.get_project_by_id(4))
    assert (project.id, project.name, project.status) == (4, "N", "active")
    for status in (403, 404, 500):
        fetch.reply(status, {})
        assert run(db.get_project_by_id(4)) is None


@pytest.mark.unit
def test_create_project_returns_new_id_or_server_message(db):
    fetch.reply(201, {"project": {"id": 31}})
    assert run(db.create_project("n", "d")) == (True, "", 31)
    fetch.reply(400, {"detail": "Name taken"})
    assert run(db.create_project("n", "d")) == (False, "Name taken", None)


@pytest.mark.unit
def test_requests_carry_the_logged_in_user_id(db):
    fetch.reply(201, {"project": {"id": 1}})
    run(db.create_project("n", "d"))
    import json
    assert json.loads(fetch.calls[0][1]["body"])["user_id"] == 7


@pytest.mark.unit
def test_return_task_to_backlog_returns_the_item(db):
    fetch.reply(200, {"backlog_item": {"id": 5}})
    assert run(db.return_task_to_backlog(1, 2, 5)) == (True, "", {"id": 5})


@pytest.mark.unit
def test_get_role_members_unwraps_members_list(db):
    fetch.reply(200, {"members": [{"user_id": 1}]})
    assert run(db.get_role_members(1, "QA")) == [{"user_id": 1}]


@pytest.mark.unit
def test_server_message_is_passed_through_on_error(db):
    fetch.reply(403, {"detail": "You need manage_tasks"})
    assert run(db.delete_task(1, 2, "5")) == (False, "You need manage_tasks")
    fetch.reply(200, {"message": "Task deleted."})
    assert run(db.delete_task(1, 2, "5")) == (True, "Task deleted.")


@pytest.mark.unit
def test_update_profile_joins_validation_errors(db):
    fetch.reply(422, {"detail": [{"msg": "too short"}, {"msg": "bad chars"}]})
    assert run(db.update_profile("x")) == (False, "too short; bad chars")


@pytest.mark.unit
def test_update_profile_only_sends_provided_fields(db):
    import json
    fetch.reply(200, {})
    run(db.update_profile(username="new"))
    assert json.loads(fetch.calls[0][1]["body"]) == {"username": "new"}


@pytest.mark.unit
def test_project_member_users_are_the_intersection(db):
    async def members(project_id):
        return {"members": [1, "3", "x"]}

    async def users():
        return [{"user_id": 1}, {"user_id": 2}, {"user_id": 3}]

    db.get_project_members, db.get_users = members, users
    assert run(db.get_project_member_users(1)) == [{"user_id": 1}, {"user_id": 3}]


@pytest.mark.unit
def test_project_member_users_empty_when_project_unreachable(db):
    async def members(project_id):
        return None

    async def users():
        return [{"user_id": 1}]

    db.get_project_members, db.get_users = members, users
    assert run(db.get_project_member_users(1)) == []