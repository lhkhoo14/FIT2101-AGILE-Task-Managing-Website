from pyodide.http import pyfetch # type: ignore
from pyscript import window       # type: ignore
import json

from constants import ACTIVE_SESSION_KEY, API_URL

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
                        status=p.get("status", "todo")
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
                    status=data.get("status", "todo")
                )
            elif response.status in (403, 404):
                print(f"[API Security] Project access denied or missing (Status {response.status}).")
                return None

            return None
        except Exception as e:
            print(f"[API Error] Failed to fetch project: {e}")
            return None
    
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
        self, project_id: int, title: str, tag: str, priority: str
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
                body=json.dumps({"user_id": user_id, "title": title, "tag": tag, "priority": priority})
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

    async def create_sprint(self, project_id: int, name: str, details: str, status: str) -> tuple[bool, str]:
        """Creates a new sprint in server database."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session expired"

        try:
            response = await pyfetch(
                f"{self.api_url}/projects/{project_id}/sprints",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"user_id": user_id, "name": name, "details": details, "status": status})
            )
            if response.status in (200, 201):
                return True, ""
            err_data = await response.json()
            return False, err_data.get("detail", "Failed to create sprint.")
        except Exception as e:
            print(f"[API Error] Failed to create sprint: {e}")
            return False, "Unable to connect to the server."

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
            return False, err_data.get("detail", "Failed to update board.")
        except Exception as e:
            print(f"[API Error] Failed to update kanban state: {e}")
            return False, "Unable to connect to the server."


class Project:
    def __init__(self, id: int, name: str, description: str, status: str) -> None:
        self.id = id
        self.name = name
        self.description = description
        self.status = status