from pyscript import window # type: ignore
from pyodide.http import pyfetch # type: ignore
import json

from models import User
from constants import STORAGE_KEY_APP_DATA
API_URL = "http://localhost:8000/api"

class ServerData:
    def __init__(self):
        self.logged_in_user_id = None

        self.next_user_id = 1
        self.next_project_id = 1
        self.users = []
        self.projects = []
        
        # Auto-load on instantiation
        self.load_data()

    def load_data(self):
        """Loads data from browser's LocalStorage."""
        raw_data = window.localStorage.getItem(STORAGE_KEY_APP_DATA)

        if raw_data:
            try:
                saved_data = json.loads(raw_data)

                self.logged_in_user_id = saved_data.get("logged_in_user_id", None)

                self.next_user_id = saved_data.get("next_user_id", 1)
                self.next_project_id = saved_data.get("next_project_id", 1)
                self.users = saved_data.get("users", [])
                self.projects = saved_data.get("projects", [])

                print("Data loaded successfully from localStorage.")
            except Exception as e:
                print(f"Error parsing stored JSON: {e}")
                self._initialize_defaults()
        else:
            print("No saved data found. Initializing defaults.")
            self._initialize_defaults()

    def _initialize_defaults(self):
        """Resets to default state and writes to storage."""
        self.logged_in_user_id = None

        self.next_user_id = 1
        self.next_project_id = 1
        self.users = []
        self.projects = []
        self.save_data()

    def save_data(self):
        """Serializes instance data and saves to browser's LocalStorage."""
        payload = {
            "logged_in_user_id": self.logged_in_user_id,
            "next_user_id": self.next_user_id,
            "next_project_id": self.next_project_id,
            "users": self.users,
            "projects": self.projects
        }
        window.localStorage.setItem(STORAGE_KEY_APP_DATA, json.dumps(payload))
        print("Data saved successfully.")

    def find_user_by_id(self, user_id: int) -> User|None:
        for user in self.users:
            if user["user_id"] == user_id:
                return User(
                    user["user_id"],
                    user["username"],
                    user["email"],
                    user["password"],
                )
        return None

    def find_user_by_email(self, email: str) -> User|None:
        for user in self.users:
            if user["email"] == email:
                return User(
                    user["user_id"],
                    user["username"],
                    user["email"],
                    user["password"],
                )
        return None

    def validate_login(self, email: str, password: str) -> bool:
        user = self.find_user_by_email(email)

        if user is None:
            return False
        else:
            if user.password == password:
                self.set_active_session(user.user_id)
                return True
            else:
                return False

    def set_active_session(self, user_id: int):
        self.logged_in_user_id = user_id
        window.localStorage.setItem("session_user_id", str(user_id))

    def get_active_session(self) -> str | None:
        return window.localStorage.getItem("session_user_id")

    def clear_session(self):
        self.logged_in_user_id = None
        window.localStorage.removeItem("session_user_id")

    async def create_project(self, name: str, description: str):
        """Creates a project through the FastAPI server."""
        user_id = self.get_active_session()

        if user_id is None:
            return False, "No user is currently logged in."

        try:
            response = await pyfetch(
                f"{API_URL}/projects",
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "user_id": int(user_id),
                    "name": name,
                    "description": description
                })
            )

            if response.status == 201:
                data = await response.json()
                return True, data["project"]

            error_data = await response.json()
            return False, error_data.get("detail", "Failed to create project.")

        except Exception as e:
            print(f"[API Error] {e}")
            return False, "Unable to connect to the server."

    async def get_projects(self):
        """Gets all projects from the FastAPI server."""
        try:
            response = await pyfetch(
                f"{API_URL}/projects",
                method="GET"
            )

            if response.status == 200:
                data = await response.json()
                return data.get("projects", [])

            return []

        except Exception as e:
            print(f"[API Error] {e}")
            return []