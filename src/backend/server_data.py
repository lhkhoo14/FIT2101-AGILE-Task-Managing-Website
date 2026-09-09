from pyodide.http import pyfetch # type: ignore
from pyscript import window       # type: ignore
import json

API_URL = "http://localhost:8000/api"

class ServerData:
    def __init__(self, session_key : str = "session_user_id"):
        self.logged_in_user_id: int | None = None
        self.session_key = session_key
        self.clear_session()
        self.load_session()

    async def register_user(self, username: str, email: str, password: str) -> tuple[bool, str]:
        """Sends registration request to FastAPI server."""
        try:
            pass
            response = await pyfetch(
                f"{API_URL}/register",
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
                f"{API_URL}/login",
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