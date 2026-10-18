from pyodide.http import pyfetch # type: ignore
from pyscript import window       # type: ignore
import asyncio
import json
from typing import Any
from urllib.parse import quote

from constants import ACTIVE_SESSION_KEY, API_URL
from project_role_helpers import permissions_for_user  # type: ignore


class Project:
    """A project record returned by the FastAPI projects endpoints."""

    def __init__(
        self,
        id: int,
        name: str,
        description: str,
        status: str,
        created_at: int | None = None,
        permissions: set[str] | None = None,
        last_edited_by: str | None = None,
        last_edited_at: str | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.status = status
        self.last_edited_by = last_edited_by
        self.last_edited_at = last_edited_at
        # Epoch milliseconds, exactly as the server stores it, and None for a
        # project that predates the field - the dashboard renders that as
        # "Unknown". Both call sites in this module pass it, so it has to be
        # accepted here or constructing a Project raises and every fetch
        # appears to return nothing.
        self.created_at = created_at
        # Permissions the signed-in user holds in this project, used only to
        # decide which destructive controls to show. The server re-checks every
        # request, so hiding a button is never what protects the data.
        self.permissions = permissions or set()


class ServerData:
    def __init__(self, session_key : str = ACTIVE_SESSION_KEY, api_url : str = API_URL):
        self.logged_in_user_id: int | None = None

        self.session_key = session_key
        self.api_url = api_url
        self.load_session()

    async def register_user(self, username: str, email: str, password: str) -> tuple[bool, str]:
        """Sends registration request to FastAPI server."""
        try:
            response = await pyfetch(
                f"{self.api_url}/register",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"username": username, "email": email, "password": password})
            )
            if response.status == 201:
                return True, ""
            else:
                err_data = await response.json()
                return False, err_data.get("detail", "Registration failed.")
        except Exception as e:
            print(f"[API Error] {e}")
            return False, "Unable to connect to the server."

    async def validate_login(self, email: str, password: str) -> tuple[bool, str]:
        """Sends login request to FastAPI server with detailed error feedback."""
        try:
            response = await pyfetch(
                f"{self.api_url}/login",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"email": email, "password": password})
            )
            data = await response.json()

            if response.status == 200:
                self.set_active_session(data["user_id"])
                return True, ""
            
            detail = data.get("detail", "Login failed.")
            # If FastAPI returns validation errors as a list of dicts, format into a string
            if isinstance(detail, list):
                detail = "; ".join([f"{err.get('msg', 'Invalid input')}" for err in detail])

            return False, str(detail)
        except Exception as e:
            print(f"[API Error] {e}")
            return False, "Unable to connect to the server."

    async def get_user_by_id(self, user_id: int) -> dict | None:
        """Fetches user details from FastAPI backend by user ID."""
        try:
            response = await pyfetch(
                f"{self.api_url}/users/{user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return None
        except Exception as e:
            print(f"[API Error] Failed to fetch user: {e}")
            return None

    async def get_users(self) -> list[dict]:
        """Fetches registered user details for sprint membership selection."""
        user_id = self.get_active_session()
        if user_id is None:
            return []

        try:
            response = await pyfetch(
                f"{self.api_url}/users?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return []
        except Exception as e:
            print(f"[API Error] Failed to fetch users: {e}")
            return []

    def get_active_session(self) -> int | None:
        """Returns currently logged in user ID."""
        return self.logged_in_user_id

    def set_active_session(self, user_id: int):
        self.logged_in_user_id = user_id
        try:
            window.localStorage.setItem(self.session_key, str(user_id))
        except Exception as e:
            print(f"[Storage Error] {e}")

    def load_session(self) -> str | None:
        """Keeps session tracking lightweight in browser localStorage."""
        session_id = window.localStorage.getItem(self.session_key)
        if session_id and session_id.isdigit():
            self.logged_in_user_id = int(session_id)

    def clear_session(self):
        self.logged_in_user_id = None
        window.localStorage.removeItem(self.session_key)

    async def create_project(self, name: str, description: str) -> tuple[bool, str, int | None]:
        """Creates a new project on the backend."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session has expired.", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id,
                    "name": name,
                    "description": description
                })
            )
            if response.status in (200, 201):
                data = await response.json()
                project_data = data.get("project", {})
                project_id = project_data.get("project_id", project_data.get("id", None))
                return True, "", project_id
            err_data = await response.json()
            return False, err_data.get("detail", "Unable to create project."), None
        except Exception as e:
            print(f"[API Error] Failed to create project: {e}")
            return False, "Unable to connect to the server.", None

    async def get_projects(self) -> list[Project] | None:
        """Fetches all projects associated with the active user session."""
        user_id = self.get_active_session()
        if user_id is None:
            return None

        try:
            response = await pyfetch(
                f"{self.api_url}/users/{user_id}/projects",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                data = await response.json()
                return [
                    Project(
                        id=p.get("project_id", p.get("id", "")),
                        name=p.get("name", "Untitled Project"),
                        description=p.get("description", "No description provided."),
                        status=p.get("status") or "active",
                        created_at=p.get("created_at"),
                        permissions=permissions_for_user(p, user_id),
                        last_edited_by=p.get("last_edited_by"),
                        last_edited_at=p.get("last_edited_at")
                    )
                    for p in data
                ]
            return None
        except Exception as e:
            print(f"[API Error] Failed to fetch projects: {e}")
            return None

    async def get_project_by_id(self, project_id: int) -> Project | None:
        """Fetches all projects associated with the active user session."""
        user_id = self.get_active_session()
        if user_id is None:
            return None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                data = await response.json()
                return Project(
                    id=data.get("project_id", data.get("id", "")),
                    name=data.get("name", "Untitled Project"),
                    description=data.get("description", "No description provided."),
                    status=data.get("status") or "active",
                    created_at=data.get("created_at"),
                    last_edited_by=data.get("last_edited_by"),
                    last_edited_at=data.get("last_edited_at")
                )
            elif response.status in (403, 404):
                print(f"[API Security] Project access denied or missing (Status {response.status}).")
                return None

            return None
        except Exception as e:
            print(f"[API Error] Failed to fetch project: {e}")
            return None
    
    async def update_project_description(
        self, project_id: int, description: str
    ) -> tuple[bool, str, dict | None]:
        """Updates a project's description and returns its audit metadata."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired.", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/description",
                method="PUT",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id,
                    "description": description
                })
            )
            data = await response.json()

            if response.status == 200:
                return True, "", data

            detail = data.get("detail", "Failed to update project description.")
            if isinstance(detail, list):
                detail = "; ".join(
                    str(error.get("msg", "Invalid input")) for error in detail
                )
            return False, str(detail), None
        except Exception as e:
            print(f"[API Error] Failed to update project description: {e}")
            return False, "Unable to connect to the server.", None

    async def update_project_status(self, project_id: int, status: str) -> tuple[bool, str]:
        """Changes a project's status (active / completed)."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired"

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/status",
                method="PATCH",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "status": status})
            )
            if response.status == 200:
                return True, ""
            err_data = await response.json()
            return False, str(err_data.get("detail", "Failed to update project status."))
        except Exception as e:
            print(f"[API Error] Failed to update project status: {e}")
            return False, "Unable to connect to the server."

    async def get_project_members(self, project_id: int) -> dict | None:
        """Fetches project members, contributors and roles from FastAPI."""
        user_id = self.get_active_session()
        if user_id is None:
            return None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/members?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()

            print(f"[API Error] Failed to fetch project members: {response.status}")
            return None
        except Exception as e:
            print(f"[API Error] Failed to fetch project members: {e}")
            return None

    async def add_project_member(self, project_id: int, username: str) -> tuple[bool, str]:
        """Adds an existing user to a project by username."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "No active session."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/members",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "username": username})
            )
            if response.status == 200:
                return True, "Member added successfully."

            data = await response.json()
            return False, data.get("detail", "Failed to add member.")
        except Exception as e:
            print(f"[API Error] Failed to add project member: {e}")
            return False, "Failed to add member."

    # --- Backlog & Sprint API Calls ---
    async def get_backlog_items(self, project_id: int) -> list[dict]:
        """Fetches product backlog items from server database."""
        user_id = self.get_active_session()
        if user_id is None:
            return []

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/backlog?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return []
        except Exception as e:
            print(f"[API Error] Failed to fetch backlog: {e}")
            return []

    async def create_backlog_item(
        self, project_id: int, title: str, tags: list[str], priority: str,
        description: str = ""
    ) -> tuple[bool, str, dict | None]:
        """Creates a new backlog task item in server database."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/backlog",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id, "title": title, "tags": tags or [],
                    "priority": priority, "description": description or ""
                })
            )
            if response.status in (200, 201):
                item = await response.json()
                return True, "", item
            err_data = await response.json()
            return False, err_data.get("detail", "Failed to create backlog item."), None
        except Exception as e:
            print(f"[API Error] Failed to create task: {e}")
            return False, "Unable to connect to the server.", None

    async def get_sprints(self, project_id: int) -> list[dict]:
        """Fetches all sprints for a project."""
        user_id = self.get_active_session()
        if user_id is None:
            return []

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return []
        except Exception as e:
            print(f"[API Error] Failed to fetch sprints: {e}")
            return []

    async def create_sprint(
        self,
        project_id: int,
        name: str,
        details: str,
        status: str,
        start_date: str,
        end_date: str,
        priority: str = "medium",
        tags: list[str] | None = None,
        members: list[int] | None = None,
        created_at: int | None = None,
    ) -> tuple[bool, str, dict | None]:
        """Creates a new sprint in server database."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id,
                    "name": name,
                    "details": details,
                    "status": status,
                    "start_date": start_date,
                    "end_date": end_date,
                    "priority": priority,
                    "tags": tags or [],
                    "members": members,
                    "created_at": created_at,
                })
            )
            if response.status in (200, 201):
                return True, "", await response.json()
            err_data = await response.json()
            detail = err_data.get("detail", "Failed to create sprint.")
            if isinstance(detail, list):  # FastAPI validation errors arrive as a list
                detail = "; ".join(str(err.get("msg", "Invalid input")) for err in detail)
            return False, str(detail), None
        except Exception as e:
            print(f"[API Error] Failed to create sprint: {e}")
            return False, "Unable to connect to the server.", None

    async def get_sprint_backlog(self, project_id: int, sprint_id: str | int) -> list[dict]:
        """Fetches backlog items assigned to a specific sprint."""
        user_id = self.get_active_session()
        if user_id is None:
            return []

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/backlog?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return []
        except Exception as e:
            print(f"[API Error] Failed to fetch sprint backlog: {e}")
            return []

    async def get_kanban_state(self, project_id: int, sprint_id: str | int) -> dict | None:
        """Fetches the kanban columns for a sprint."""
        user_id = self.get_active_session()
        if user_id is None:
            return None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/kanban?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return None
        except Exception as e:
            print(f"[API Error] Failed to fetch kanban state: {e}")
            return None

    async def get_project_kanban_states(self, project_id: int) -> dict:
        """Fetches every sprint's kanban board for a project in one request.

        CHANGE: replaces one kanban request per sprint. A project with N sprints
        went from N sequential round trips down to 1. Results are keyed by the
        sprint id as a string, matching how the backend serialises them.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return {}

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/kanban-states?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return {}
        except Exception as e:
            print(f"[API Error] Failed to fetch kanban states: {e}")
            return {}

    async def move_backlog_item_to_sprint(
        self, project_id: int, backlog_id: str | int, sprint_id: str | int
    ) -> tuple[bool, str]:
        """Assigns/moves a backlog item into a sprint."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired"

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/backlog",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "backlog_id": int(backlog_id)})
            )
            if response.status in (200, 201):
                return True, ""
            err_data = await response.json()
            return False, err_data.get("detail", "Failed to move item to sprint.")
        except Exception as e:
            print(f"[API Error] Failed to move backlog item: {e}")
            return False, "Unable to connect to the server."

    async def return_task_to_backlog(
        self, project_id: int, sprint_id: str | int, task_id: str | int
    ) -> tuple[bool, str, dict | None]:
        """Moves a task still in a sprint's backlog column back to the product backlog."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/return-to-backlog",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id})
            )
            if response.status in (200, 201):
                data = await response.json()
                return True, "", data.get("backlog_item")
            err_data = await response.json()
            detail = err_data.get("detail", "Failed to return task to the product backlog.")
            if isinstance(detail, list):
                detail = "; ".join(str(err.get("msg", "Invalid input")) for err in detail)
            return False, str(detail), None
        except Exception as e:
            print(f"[API Error] Failed to return task to backlog: {e}")
            return False, "Unable to connect to the server.", None

    async def update_kanban_state(
        self, project_id: int, sprint_id: str | int, kanban_state: dict
    ) -> tuple[bool, str]:
        """Saves current Kanban column state to the backend."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired"

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/kanban",
                method="PUT",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "state": kanban_state})
            )
            if response.status == 200:
                return True, ""
            err_data = await response.json()
            detail = err_data.get("detail", "Failed to update board.")
            if isinstance(detail, list):
                detail = "; ".join(str(err.get("msg", "Invalid input")) for err in detail)
            return False, str(detail)
        except Exception as e:
            print(f"[API Error] Failed to update kanban state: {e}")
            return False, "Unable to connect to the server."

    async def update_sprint_status(
        self, project_id: int, sprint_id: str | int, status: str
    ) -> tuple[bool, str, dict | None]:
        """Updates the sprint status on the backend."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/status",
                method="PATCH",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "status": status})
            )
            if response.status == 200:
                data = await response.json()
                return True, "", data.get("sprint")
            err_data = await response.json()
            return False, err_data.get("detail", "Failed to update sprint status."), None
        except Exception as e:
            print(f"[API Error] Failed to update sprint status: {e}")
            return False, "Unable to connect to the server.", None

    async def get_account_settings(self) -> tuple[bool, Any]:
        """The signed-in user's settings payload, or a message explaining why not.

        The second value is the payload (a dict) when the first is True, and a
        human-readable message when it is False - the shape every account method
        in this class returns, which is why the caller checks `success` first.
        """
        user_id = self.get_active_session()
        if not user_id:
            return False, "Session has expired."
        try:
            response = await pyfetch(f"{self.api_url}/users/{user_id}/settings", method="GET")
            data = await response.json()
            if response.status == 200:
                return True, data
            return False, data.get("detail", "Failed to load settings.")
        except Exception as e:
            return False, str(e)

    async def update_profile(self, username=None, profile_photo=None) -> tuple[bool, Any]:
        user_id = self.get_active_session()
        if not user_id:
            return False, "Session has expired."
        try:
            payload = {}
            if username is not None:
                payload["username"] = username
            if profile_photo is not None:
                payload["profile_photo"] = profile_photo
            response = await pyfetch(
                f"{self.api_url}/users/{user_id}/profile",
                method="PATCH",
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload)
            )
            data = await response.json()
            if response.status == 200:
                return True, data
            detail = data.get("detail", "Failed to update profile.")
            if isinstance(detail, list):
                detail = "; ".join([err.get("msg", str(err)) for err in detail])
            return False, detail
        except Exception as e:
            return False, str(e)

    async def request_email_change(self, new_email) -> tuple[bool, Any]:
        user_id = self.get_active_session()
        if not user_id:
            return False, "Session has expired."
        try:
            response = await pyfetch(
                f"{self.api_url}/users/{user_id}/email-change",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"new_email": new_email})
            )
            data = await response.json()
            if response.status == 200:
                return True, data
            detail = data.get("detail", "Failed to request email change.")
            if isinstance(detail, list):
                detail = "; ".join([err.get("msg", str(err)) for err in detail])
            return False, detail
        except Exception as e:
            return False, str(e)

    async def verify_email_change(self, token) -> tuple[bool, Any]:
        try:
            response = await pyfetch(
                f"{self.api_url}/users/email-verify",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"token": token})
            )
            data = await response.json()
            if response.status == 200:
                return True, data
            detail = data.get("detail", "Verification failed.")
            if isinstance(detail, list):
                detail = "; ".join([err.get("msg", str(err)) for err in detail])
            return False, detail
        except Exception as e:
            return False, str(e)

    async def change_password(self, current_password, new_password) -> tuple[bool, Any]:
        user_id = self.get_active_session()
        if not user_id:
            return False, "Session has expired."
        try:
            response = await pyfetch(
                f"{self.api_url}/users/{user_id}/password",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"current_password": current_password, "new_password": new_password})
            )
            data = await response.json()
            if response.status == 200:
                return True, data
            detail = data.get("detail", "Failed to change password.")
            if isinstance(detail, list):
                detail = "; ".join([err.get("msg", str(err)) for err in detail])
            return False, detail
        except Exception as e:
            return False, str(e)

    async def get_project_member_users(self, project_id: int) -> list[dict]:
        """Registered users who belong to this project, and only those.

        US-19: the sprint create/edit dialog must not offer accounts that are not
        part of the parent project. Members and users are independent requests, so
        they are fetched concurrently and then intersected here.
        """
        payload, users = await asyncio.gather(
            self.get_project_members(project_id),
            self.get_users(),
        )
        member_ids = {
            int(member_id)
            for member_id in (payload or {}).get("members", []) or []
            if str(member_id).isdigit()
        }
        return [user for user in users or [] if int(user["user_id"]) in member_ids]

    async def get_change_history(self, project_id: int) -> list[dict]:
        """US-20: the project's change history, newest first, from the server."""
        user_id = self.get_active_session()
        if user_id is None:
            return []

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/history?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return []
        except Exception as e:
            print(f"[API Error] Failed to fetch change history: {e}")
            return []

    async def record_change(self, project_id: int, message: str, action: str = "project_change",
                            sprint_id=None, sprint_name=None, task_id=None, task_title=None,
                            from_status=None, to_status=None, timestamp=None) -> tuple[bool, str]:
        """US-20: append one event to the project's audit trail on the server.

        The server stamps the time and actor, so the feed reads the same on every
        device. `timestamp` is only used by the one-time browser-data migration.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired"

        body = {
            "user_id": user_id,
            "action": action,
            "message": message,
            "sprint_id": str(sprint_id) if sprint_id is not None else None,
            "sprint_name": sprint_name,
            "task_id": str(task_id) if task_id is not None else None,
            "task_title": task_title,
            "from_status": from_status,
            "to_status": to_status,
        }
        if timestamp:
            body["timestamp"] = timestamp

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/history",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps(body)
            )
            if response.status in (200, 201):
                return True, ""
            err_data = await response.json()
            return False, err_data.get("detail", "Failed to save change history.")
        except Exception as e:
            print(f"[API Error] Failed to save change history: {e}")
            return False, "Unable to connect to the server."

    async def get_contributions(self, project_id: int) -> dict:
        """US-20: member contribution statistics calculated and stored server-side."""
        user_id = self.get_active_session()
        if user_id is None:
            return {}

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/contributions?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return {}
        except Exception as e:
            print(f"[API Error] Failed to fetch contributions: {e}")
            return {}

    async def log_task_time(self, project_id: int, sprint_id, task_id, action: str
                            ) -> tuple[bool, str, dict | None]:
        """US-21: start/stop a work session on a task.

        The server owns the timestamps and stamps the record with the acting User
        ID and the Task ID, then returns the updated time log for the task.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired", None

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/time-log",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "action": action})
            )
            if response.status == 200:
                return True, "", await response.json()
            err_data = await response.json()
            return False, err_data.get("detail", "Failed to update the task time log."), None
        except Exception as e:
            print(f"[API Error] Failed to log task time: {e}")
            return False, "Unable to connect to the server.", None


    async def create_project_role(
        self,
        project_id: int,
        name: str,
        colour: str,
        description: str,
        permissions: list[str],
        conflicting_roles: list[str],
    ) -> tuple[bool, str]:
        """Sends a request to create a custom project role."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/roles",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id,
                    "name": name,
                    "colour": colour,
                    "description": description,
                    "permissions": permissions,
                    "conflicting_roles": conflicting_roles
                })
            )
            if response.status in (200, 201):
                return True, "Role created successfully."
            
            data = await response.json()
            return False, data.get("detail", "Failed to create role.")
        except Exception as e:
            print(f"[API Error] Failed to create role: {e}")
            return False, "Unable to connect to the server."

    async def delete_project_role(self, project_id: int, role_name: str) -> tuple[bool, str]:
        """Deletes a custom project role."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/roles/{role_name}",
                method="DELETE",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id})
            )
            if response.status == 200:
                return True, "Role deleted successfully."
            
            data = await response.json()
            return False, data.get("detail", "Failed to delete role.")
        except Exception as e:
            print(f"[API Error] Failed to delete role: {e}")
            return False, "Unable to connect to the server."

    async def update_project_role(self, project_id: int, role_name: str, colour: str, description: str, permissions: list, conflicting_roles: list) -> tuple[bool, str]:
        """Updates an existing custom project role."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/roles/{role_name}",
                method="PUT",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id,
                    "colour": colour,
                    "description": description,
                    "permissions": permissions,
                    "conflicting_roles": conflicting_roles
                })
            )
            if response.status == 200:
                return True, "Role updated successfully."
            
            data = await response.json()
            return False, data.get("detail", "Failed to update role.")
        except Exception as e:
            print(f"[API Error] Failed to update role: {e}")
            return False, "Unable to connect to the server."

    async def get_role_members(self, project_id: int, role_name: str) -> list:
        user_id = self.get_active_session()
        if user_id is None:
            return []
        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/roles/{role_name}/members?user_id={user_id}",
                method="GET"
            )
            if response.status == 200:
                data = await response.json()
                return data.get("members", [])
        except Exception as e:
            print(f"[API Error] Failed to fetch role members: {e}")
        return []

    async def remove_role_member(self, project_id: int, role_name: str, target_user_id: int) -> tuple[bool, str]:
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."
        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/roles/{role_name}/remove",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "target_user_id": target_user_id})
            )
            if response.status == 200:
                return True, "Member removed from role successfully."
            data = await response.json()
            return False, data.get("detail", "Failed to remove member.")
        except Exception as e:
            return False, "Unable to connect to server."

    async def assign_project_role(self, project_id: int, role_name: str, target_user_id: int) -> tuple[bool, str]:
        """Assigns a project role to a member."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."
        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/roles/assign",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": user_id, 
                    "target_user_id": target_user_id, 
                    "role_name": role_name
                })
            )
            if response.status == 200:
                return True, "Role assigned successfully."
            data = await response.json()
            return False, data.get("detail", "Failed to assign role.")
        except Exception as e:
            return False, "Unable to connect to server."

    async def get_all_users(self) -> list[dict]:
        """Fetches all registered users."""
        user_id = self.get_active_session()
        if user_id is None:
            return []
        try:
            response = await pyfetch(
                f"{self.api_url}/users?user_id={user_id}",
                method="GET",
                headers={"Content-Type": "application/json"}
            )
            if response.status == 200:
                return await response.json()
            return []
        except Exception as e:
            print(f"[API Error] Failed to fetch users: {e}")
            return []

    async def delete_project(self, project_id: int) -> tuple[bool, str]:
        """Deletes a project and everything stored inside it (delete_project)."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}",
                method="DELETE",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id})
            )
            data = await response.json()
            if response.status == 200:
                return True, data.get("message", "Project deleted.")
            return False, data.get("detail", "Failed to delete project.")
        except Exception as e:
            print(f"[API Error] Failed to delete project: {e}")
            return False, "Unable to connect to the server."

    async def delete_sprint(self, project_id: int, sprint_id: str | int) -> tuple[bool, str]:
        """Deletes one sprint, with everything on its board.

        Refused by the server for a completed sprint, which is kept as the record
        of what the team finished.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}",
                method="DELETE",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id})
            )
            data = await response.json()
            if response.status == 200:
                return True, data.get("message", "Sprint deleted.")
            return False, data.get("detail", "Failed to delete sprint.")
        except Exception as e:
            print(f"[API Error] Failed to delete sprint: {e}")
            return False, "Unable to connect to the server."

    async def delete_task(self, project_id: int, sprint_id: str | int,
                          task_id: str) -> tuple[bool, str]:
        """Deletes one task from a sprint board.

        Needs manage_tasks (every preset role holds it), and is refused by the
        server for a task sitting in Completed.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints/{sprint_id}"
                f"/tasks/{quote(str(task_id))}",
                method="DELETE",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id})
            )
            data = await response.json()
            if response.status == 200:
                return True, data.get("message", "Task deleted.")
            return False, data.get("detail", "Failed to delete task.")
        except Exception as e:
            print(f"[API Error] Failed to delete task: {e}")
            return False, "Unable to connect to the server."

    async def remove_project_member(self, project_id: int, member_id: int) -> tuple[bool, str]:
        """Removes a member from a project (manage_members).

        The member's account is untouched: they lose this project, not their
        user record.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/members/{member_id}/remove",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id})
            )
            data = await response.json()
            if response.status == 200:
                return True, data.get("message", "Member removed.")
            return False, data.get("detail", "Failed to remove member.")
        except Exception as e:
            print(f"[API Error] Failed to remove member: {e}")
            return False, "Unable to connect to the server."

    async def delete_account(self, password: str) -> tuple[bool, str]:
        """Deletes the signed-in account and unlinks it from every project.

        Self-service: the password is what proves the account is the caller's.
        """
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired."

        try:
            response = await pyfetch(
                f"{self.api_url}/users/{user_id}/delete",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"password": password})
            )
            data = await response.json()
            if response.status == 200:
                return True, data.get("message", "Account deleted.")
            return False, data.get("detail", "Failed to delete account.")
        except Exception as e:
            print(f"[API Error] Failed to delete account: {e}")
            return False, "Unable to connect to the server."