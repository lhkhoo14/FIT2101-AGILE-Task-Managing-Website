import json
import os
from typing import Any, Dict, Optional

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "data",
    "server_database.json"
)

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db_directory()

    def _ensure_db_directory(self) -> None:
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)

    def _default_structure(self) -> Dict[str, Any]:
        return {
            "next_user_id": 1,
            "next_project_id": 1,
            "next_backlog_id": 1,
            "next_sprint_id": 1,
            "users": [],
            "projects": {}
        }

    def read(self) -> Dict[str, Any]:
        if not os.path.exists(self.db_path):
            return self._default_structure()

        try:
            with open(self.db_path, "r") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return self._default_structure()
                for key, default in self._default_structure().items():
                    data.setdefault(key, default)
                return data
        except (json.JSONDecodeError, Exception):
            return self._default_structure()

    def write(self, data: Dict[str, Any]) -> None:
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=4)

    # --- Query Helpers ---
    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        db = self.read()
        return next((u for u in db["users"] if u["email"].lower() == email.lower()), None)

    def find_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        db = self.read()
        return next((u for u in db["users"] if u["user_id"] == user_id), None)

db_manager = DatabaseManager()