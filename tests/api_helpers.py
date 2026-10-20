"""Small helpers that build realistic state through the public API."""
from datetime import date, timedelta

PASSWORD = "Password123!"


def verify_account(client, user_id):
    """Verify a freshly registered account, the way a user would with the emailed code.

    The code is read from the (temporary) test database, because the mailer is
    offline in tests and nothing is actually sent.
    """
    from database_manager import db_manager  # type: ignore # the app's own copy, redirected by conftest

    user = next(u for u in db_manager.read()["users"] if u["user_id"] == user_id)
    response = client.post(
        "/api/verify-code", json={"email": user["email"], "code": user["verify_code"]}
    )
    assert response.status_code == 200, response.text


def register(client, username, email=None, password=PASSWORD, verify=True):
    """Register a user. Accounts must be verified before they can log in, so by
    default this verifies too; pass verify=False to keep the account unverified."""
    email = email or f"{username}@monash.edu"
    response = client.post("/api/register", json={"username": username, "email": email, "password": password})
    assert response.status_code == 201, response.text
    user_id = response.json()["user_id"]
    if verify:
        verify_account(client, user_id)
    return user_id


def create_project(client, user_id, name="Alpha", description="A project"):
    response = client.post("/api/projects", json={"user_id": user_id, "name": name, "description": description})
    assert response.status_code == 201, response.text
    return response.json()["project"]


def add_member(client, project_id, actor_id, username):
    response = client.post(f"/api/projects/{project_id}/members", json={"user_id": actor_id, "username": username})
    assert response.status_code == 200, response.text
    return response.json()


def create_sprint(client, project_id, user_id, name="Sprint 1", start=0, end=14, **extra):
    body = {
        "user_id": user_id,
        "name": name,
        "details": "details",
        "status": "active",
        "start_date": (date.today() + timedelta(days=start)).isoformat(),
        "end_date": (date.today() + timedelta(days=end)).isoformat(),
    }
    body.update(extra)
    response = client.post(f"/api/projects/{project_id}/sprints", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def create_backlog_item(client, project_id, user_id, title="Task", **extra):
    body = {"user_id": user_id, "title": title, "priority": "medium", "tags": ["api"]}
    body.update(extra)
    response = client.post(f"/api/projects/{project_id}/backlog", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def team(client):
    """A project with a creator (1), an employee (2) and an outsider (3)."""
    creator = register(client, "alice")
    employee = register(client, "bob")
    outsider = register(client, "carol")
    project = create_project(client, creator)
    add_member(client, project["project_id"], creator, "bob")
    return creator, employee, outsider, project["project_id"]


def board(**columns):
    state = {"backlog": [], "active": [], "review": [], "completed": []}
    state.update(columns)
    return state