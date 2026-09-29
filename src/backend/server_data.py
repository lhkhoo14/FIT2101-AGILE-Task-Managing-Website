from pyodide.http import pyfetch # type: ignore
from pyscript import window       # type: ignore
import json

class ServerData:
    def __init__(self, session_key : str = "session_user_id", api_url : str = "http://localhost:8000/api"):
        self.logged_in_user_id: int | None = None

        self.session_key = session_key
        self.api_url = api_url
        self.load_session()

    async def register_user(self, username: str, email: str, password: str) -> tuple[bool, str]:
        """Sends registration request to FastAPI server."""
        try:
            pass
            response = await pyfetch(
                f"{self.api_url}/register",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"username": username, "email": email, "password": password})
            )
            if response.status == 201:
                data = await response.json()
                # self.set_active_session(data["user_id"])
                return True, ""
            else:
                err_data = await response.json()
                return False, err_data.get("detail", "Registration failed.")
        except Exception as e:
            print(f"[API Error] {e}")
            return False, "Unable to connect to the server."

    async def validate_login(self, email: str, password: str) -> bool:
        """Sends login request to FastAPI server."""
        try:
            response = await pyfetch(
                f"{self.api_url}/login",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({"email": email, "password": password})
            )
            if response.status == 200:
                data = await response.json()
                self.set_active_session(data["user_id"])
                return True
            return False
        except Exception as e:
            print(f"[API Error] {e}")
            return False

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

    async def create_project(self, name: str, description: str) -> tuple[bool, str]:
        """Creates a new project on the backend."""
        user_id = self.get_active_session()
        if user_id is None:
            return False, "Session has expired."

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
                return True, ""
            err_data = await response.json()
            return False, err_data.get("detail", "Unable to create project.")
        except Exception as e:
            print(f"[API Error] Failed to create project: {e}")
            return False, "Unable to connect to the server."