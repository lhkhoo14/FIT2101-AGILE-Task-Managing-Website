import json
import os
from typing import Any, Callable, Dict, Optional, TypeVar

import psycopg

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "data",
    "server_database.json"
)
DATABASE_URL = os.getenv("DATABASE_URL")
T = TypeVar("T")

class DatabaseManager:
    """Persist application state in PostgreSQL or the local JSON fallback."""

    def __init__(self, db_path: str = DB_PATH, database_url: str | None = DATABASE_URL):
        self.db_path = db_path
        self.database_url = database_url
        self._ensure_db_directory()
        if self.database_url:
            self._initialize_postgres()

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
        if self.database_url:
            with psycopg.connect(self.database_url) as connection:
                row = connection.execute(
                    "SELECT data FROM application_state WHERE state_id = TRUE"
                ).fetchone()
                return row[0] if row else self._default_structure()
        return self._read_json()

    def _read_json(self) -> Dict[str, Any]:
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
        if self.database_url:
            with psycopg.connect(self.database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO application_state (state_id, data)
                    VALUES (TRUE, %s)
                    ON CONFLICT (state_id) DO UPDATE SET data = EXCLUDED.data
                    """,
                    (json.dumps(data),),
                )
            return
        with open(self.db_path, "w") as f:
            json.dump(data, f, indent=4)

    def update(self, mutator: Callable[[Dict[str, Any]], T]) -> T:
        """Read, mutate, and save the state atomically when PostgreSQL is active."""
        if not self.database_url:
            data = self._read_json()
            result = mutator(data)
            self.write(data)
            return result

        with psycopg.connect(self.database_url) as connection:
            row = connection.execute(
                "SELECT data FROM application_state WHERE state_id = TRUE FOR UPDATE"
            ).fetchone()
            data = row[0] if row else self._default_structure()
            result = mutator(data)
            connection.execute(
                """
                INSERT INTO application_state (state_id, data)
                VALUES (TRUE, %s)
                ON CONFLICT (state_id) DO UPDATE SET data = EXCLUDED.data
                """,
                (json.dumps(data),),
            )
            return result

    def _initialize_postgres(self) -> None:
        # Import the legacy JSON database only when the PostgreSQL row is empty.
        legacy_data = self._read_json()
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS application_state (
                    state_id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (state_id),
                    data JSONB NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO application_state (state_id, data)
                VALUES (TRUE, %s)
                ON CONFLICT (state_id) DO NOTHING
                """,
                (json.dumps(legacy_data),),
            )

    # --- Query Helpers ---
    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        db = self.read()
        return next((u for u in db["users"] if u["email"].lower() == email.lower()), None)

    def find_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        db = self.read()
        return next((u for u in db["users"] if u["user_id"] == user_id), None)

db_manager = DatabaseManager()