"""Project, member, backlog and role routes."""
import pytest

from api_helpers import add_member, create_backlog_item, create_project, create_sprint, register, team


# ---- projects -------------------------------------------------------------
@pytest.mark.api
def test_create_and_list_projects(client):
    alice, bob = register(client, "alice"), register(client, "bob")
    project = create_project(client, alice, "Alpha")
    assert project["status"] == "active" and project["created_at"] > 0
    assert project["roles"]["Project Creator"] == [alice]
    assert set(project["role_definitions"]) >= {"Project Creator", "Scrum Master", "Employee"}

    listed = client.get(f"/api/users/{alice}/projects")
    assert [p["name"] for p in listed.json()] == ["Alpha"]
    assert client.get(f"/api/users/{bob}/projects").json() == []
    assert client.get("/api/users/99/projects").status_code == 404


@pytest.mark.api
def test_get_project_requires_membership(client):
    alice, _, outsider, pid = team(client)
    assert client.get(f"/api/projects/{pid}", params={"user_id": alice}).status_code == 200
    assert client.get(f"/api/projects/{pid}", params={"user_id": outsider}).status_code == 403
    assert client.get("/api/projects/999", params={"user_id": alice}).status_code == 404


@pytest.mark.api
def test_legacy_project_gets_status_and_created_at_defaults(client, seed_factory):
    seed_factory(users=[{"user_id": 1, "username": "a", "email": "a@x.com"}],
                 projects=[{"project_id": 4, "name": "Old", "members": [1]}])
    body = client.get("/api/projects/4", params={"user_id": 1}).json()
    assert body["status"] == "active" and body["created_at"] is None


@pytest.mark.api
def test_update_project_status(client):
    alice, bob, _, pid = team(client)
    url = f"/api/projects/{pid}/status"
    assert client.patch(url, json={"user_id": alice, "status": "paused"}).status_code == 422
    assert client.patch(url, json={"user_id": 999, "status": "completed"}).status_code == 403
    done = client.patch(url, json={"user_id": alice, "status": "completed"})
    assert done.status_code == 200 and done.json()["project"]["status"] == "completed"
    assert client.patch(url, json={"user_id": bob, "status": "active"}).status_code == 403
    assert client.patch(url, json={"user_id": alice, "status": "completed"}).status_code == 200


@pytest.mark.api
def test_delete_project_needs_permission_and_cleans_user_lists(client, db):
    alice, bob, _, pid = team(client)
    url = f"/api/projects/{pid}"
    assert client.request("DELETE", url, json={"user_id": bob}).status_code == 403
    assert client.request("DELETE", "/api/projects/999", json={"user_id": alice}).status_code == 404
    response = client.request("DELETE", url, json={"user_id": alice})
    assert response.status_code == 200 and "deleted" in response.json()["message"]
    state = db.read()
    assert state["projects"] == {} and all(pid not in u.get("projects", []) for u in state["users"])


# ---- members --------------------------------------------------------------
@pytest.mark.api
def test_members_endpoint_repairs_old_role_maps(client, seed_factory):
    seed_factory(users=[{"user_id": 1, "username": "a", "email": "a@x.com"},
                        {"user_id": 2, "username": "b", "email": "b@x.com"}],
                 projects=[{"project_id": 8, "members": [1, 2], "creator": [1], "roles": {}}])
    body = client.get("/api/projects/8/members", params={"user_id": 1}).json()
    assert body["roles"]["Project Creator"] == [1] and body["roles"]["Employee"] == [2]
    assert body["contribute"] == [1, 2]
    assert "manage_roles" in body["role_definitions"]["Project Creator"]["permissions"]


@pytest.mark.api
def test_add_member_rules(client):
    alice, bob, outsider, pid = team(client)
    url = f"/api/projects/{pid}/members"
    assert client.post(url, json={"user_id": alice, "username": "bob"}).status_code == 409
    assert client.post(url, json={"user_id": alice, "username": "nobody"}).status_code == 404
    assert client.post(url, json={"user_id": bob, "username": "carol"}).status_code == 403   # Employee: no manage_members
    assert client.post("/api/projects/999/members", json={"user_id": alice, "username": "carol"}).status_code == 404
    added = client.post(url, json={"user_id": alice, "username": "carol"})
    assert added.status_code == 200 and added.json()["role"] == "Employee"
    assert outsider in client.get(f"{url}", params={"user_id": alice}).json()["roles"]["Employee"]


@pytest.mark.api
def test_remove_member_rules(client, db):
    alice, bob, outsider, pid = team(client)
    url = lambda m: f"/api/projects/{pid}/members/{m}/remove"
    assert client.post(url(bob), json={"user_id": bob}).status_code == 403          # no manage_members
    assert client.post(url(outsider), json={"user_id": alice}).status_code == 404   # not a member
    assert client.post(url(alice), json={"user_id": alice}).status_code == 400      # sole creator
    assert client.post("/api/projects/999/members/1/remove", json={"user_id": alice}).status_code == 404

    removed = client.post(url(bob), json={"user_id": alice})
    assert removed.status_code == 200 and removed.json()["member_id"] == bob
    project = db.read()["projects"][str(pid)]
    assert bob not in project["members"]
    assert project["history"][-1]["action"] == "removed_member"


@pytest.mark.api
def test_cannot_remove_an_equal_or_higher_rank(client, db):
    alice, bob, _, pid = team(client)
    # Promote bob to Scrum Master, add a second Scrum-Master-level peer via Manager role.
    assert client.post(f"/api/projects/{pid}/roles/assign",
                       json={"user_id": alice, "target_user_id": bob, "role_name": "Scrum Master"}).status_code == 200
    response = client.post(f"/api/projects/{pid}/members/{alice}/remove", json={"user_id": bob})
    assert response.status_code in (400, 403)    # sole creator or outranked, never allowed


# ---- backlog --------------------------------------------------------------
@pytest.mark.api
def test_backlog_create_and_list(client):
    alice, _, outsider, pid = team(client)
    item = create_backlog_item(client, pid, alice, "Login page", tags=["#UI", "ui", "Web"], description="  text  ")
    assert item["tags"] == ["ui", "web"] and item["description"] == "text" and item["id"] == 1
    legacy = create_backlog_item(client, pid, alice, "Old", tags=[], tag="Legacy")
    assert legacy["tags"] == ["legacy"] and legacy["id"] == 2
    listed = client.get(f"/api/projects/{pid}/backlog", params={"user_id": alice})
    assert [i["title"] for i in listed.json()] == ["Login page", "Old"]
    assert client.get(f"/api/projects/{pid}/backlog", params={"user_id": outsider}).status_code == 403
    too_long = client.post(f"/api/projects/{pid}/backlog",
                           json={"user_id": alice, "title": "x", "priority": "low", "description": "d" * 1001})
    assert too_long.status_code == 422
    assert client.post("/api/projects/999/backlog",
                       json={"user_id": alice, "title": "x", "priority": "low"}).status_code == 404


# ---- roles ----------------------------------------------------------------
def role_payload(user_id, **extra):
    body = {"user_id": user_id, "name": "QA", "colour": "#123456", "description": "tests",
            "permissions": ["review_tasks"], "conflicting_roles": []}
    body.update(extra)
    return body


@pytest.mark.api
def test_create_update_delete_custom_role(client, db):
    alice, bob, _, pid = team(client)
    base = f"/api/projects/{pid}/roles"
    assert client.post(base, json=role_payload(bob)).status_code == 403
    assert client.post(base, json=role_payload(alice, name="   ")).status_code == 422
    assert client.post("/api/projects/999/roles", json=role_payload(alice)).status_code == 404
    created = client.post(base, json=role_payload(alice))
    assert created.status_code == 201 and created.json()["role"]["name"] == "QA"
    assert client.post(base, json=role_payload(alice)).status_code == 409

    update = {"user_id": alice, "colour": "#000", "description": None, "permissions": ["manage_tasks"], "conflicting_roles": None}
    changed = client.put(f"{base}/QA", json=update)
    assert changed.status_code == 200
    assert db.read()["projects"][str(pid)]["role_definitions"]["QA"]["permissions"] == ["manage_tasks"]
    assert client.put(f"{base}/Ghost", json=update).status_code == 404
    assert client.put(f"{base}/Project Creator", json=update).status_code == 400
    assert client.put("/api/projects/999/roles/QA", json=update).status_code == 404
    assert client.put(f"{base}/QA", json={**update, "user_id": bob}).status_code == 403

    assert client.request("DELETE", f"{base}/Employee", json={"user_id": alice}).status_code == 400
    assert client.request("DELETE", f"{base}/Ghost", json={"user_id": alice}).status_code == 404
    assert client.request("DELETE", "/api/projects/999/roles/QA", json={"user_id": alice}).status_code == 404
    assert client.request("DELETE", f"{base}/QA", json={"user_id": bob}).status_code == 403
    state = db.read()
    state["projects"][str(pid)]["role_conflicts"] = {"QA": ["x"], "Other": ["QA"]}
    db.write(state)
    assert client.request("DELETE", f"{base}/QA", json={"user_id": alice}).status_code == 200
    assert "QA" not in db.read()["projects"][str(pid)]["role_definitions"]
    assert db.read()["projects"][str(pid)]["role_conflicts"]["Other"] == []


@pytest.mark.api
def test_assign_role_rules(client):
    alice, bob, outsider, pid = team(client)
    carol = outsider
    add_member(client, pid, alice, "carol")
    base = f"/api/projects/{pid}/roles"
    client.post(base, json=role_payload(alice, name="Auditor", conflicting_roles=["Manager"]))
    assign = lambda actor, target, role: client.post(f"{base}/assign", json={"user_id": actor, "target_user_id": target, "role_name": role})

    assert assign(bob, carol, "Manager").status_code == 403            # no manage_roles
    assert assign(alice, 999, "Manager").status_code == 404            # not a member
    assert assign(alice, bob, "Imaginary").status_code == 422
    assert client.post("/api/projects/999/roles/assign", json={"user_id": 1, "target_user_id": 1, "role_name": "x"}).status_code == 404
    assert assign(alice, bob, "Manager").status_code == 200
    assert assign(alice, bob, "Manager").status_code == 200            # idempotent
    assert assign(alice, bob, "Auditor").status_code == 422            # conflicts with Manager
    assert assign(alice, carol, "Auditor").status_code == 200
    assert assign(alice, carol, "Manager").status_code == 422          # reverse direction of the same conflict

    assert assign(alice, bob, "Scrum Master").status_code == 200
    assert assign(alice, carol, "Scrum Master").status_code == 422     # single-seat role already filled


@pytest.mark.api
def test_role_members_and_removal(client):
    alice, bob, _, pid = team(client)
    base = f"/api/projects/{pid}/roles"
    members = client.get(f"{base}/Employee/members", params={"user_id": alice})
    assert members.status_code == 200 and [m["username"] for m in members.json()["members"]] == ["bob"]
    assert client.get(f"{base}/Nope/members", params={"user_id": alice}).status_code == 404
    assert client.get("/api/projects/999/roles/Employee/members", params={"user_id": alice}).status_code == 404

    remove = lambda actor, target, role: client.post(f"{base}/{role}/remove", json={"user_id": actor, "target_user_id": target})
    assert remove(bob, bob, "Employee").status_code == 403
    assert remove(alice, alice, "Project Creator").status_code == 400
    assert remove(alice, bob, "Employee").status_code == 200
    assert client.get(f"{base}/Employee/members", params={"user_id": alice}).json()["members"] == []
    assert remove(alice, bob, "Employee").status_code == 200          # already gone: still fine
    assert client.post("/api/projects/999/roles/Employee/remove", json={"user_id": 1, "target_user_id": 1}).status_code == 404


@pytest.mark.api
def test_sprints_use_projects_helpers(client):
    """Sprint creation relies on the project's role map being repaired; a smoke test of that link."""
    alice, _, _, pid = team(client)
    assert create_sprint(client, pid, alice)["members"][0] == alice