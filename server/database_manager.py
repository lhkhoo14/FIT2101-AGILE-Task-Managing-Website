import json
import os
import threading
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
        # One connection reused per worker thread. FastAPI runs these sync
        # endpoints in a thread pool that is reused between requests, and psycopg
        # connections are not thread-safe, so a thread-local connection removes
        # the TCP + TLS handshake from every query without ever sharing a
        # connection across threads.
        self._local = threading.local()
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

    def _connection(self):
        """This thread's reusable connection, opening one if needed."""
        connection = getattr(self._local, "connection", None)
        if connection is None or connection.closed:
            # Supabase's transaction pooler can reuse a connection for different
            # transactions, so avoid psycopg prepared statements on pooled URLs.
            connection = psycopg.connect(self.database_url, prepare_threshold=None)
            self._local.connection = connection
        return connection

    def _drop_connection(self) -> None:
        """Discard this thread's connection so the next call reconnects cleanly."""
        connection = getattr(self._local, "connection", None)
        self._local.connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _end_transaction(self, connection) -> None:
        """Close any open transaction so no snapshot is held open and the pooled
        connection can be handed straight back."""
        try:
            connection.rollback()
        except Exception:
            self._drop_connection()

    def read(self) -> Dict[str, Any]:
        if not self.database_url:
            return self._read_json()

        connection = self._connection()
        try:
            row = connection.execute(
                "SELECT data FROM application_state WHERE state_id = TRUE"
            ).fetchone()
        except Exception:
            self._drop_connection()
            raise
        finally:
            self._end_transaction(connection)

        return row[0] if row else self._default_structure()

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
        if not self.database_url:
            with open(self.db_path, "w") as f:
                json.dump(data, f, indent=4)
            return

        connection = self._connection()
        try:
            connection.execute(
                """
                INSERT INTO application_state (state_id, data)
                VALUES (TRUE, %s)
                ON CONFLICT (state_id) DO UPDATE SET data = EXCLUDED.data
                """,
                (json.dumps(data),),
            )
            connection.commit()
        except Exception:
            self._drop_connection()
            raise
        finally:
            self._end_transaction(connection)

    def update(self, mutator: Callable[[Dict[str, Any]], T]) -> T:
        """Read, mutate, and save the state atomically when PostgreSQL is active."""
        if not self.database_url:
            data = self._read_json()
            result = mutator(data)
            self.write(data)
            return result

        connection = self._connection()
        try:
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
            connection.commit()
            return result
        except Exception:
            self._drop_connection()
            raise
        finally:
            self._end_transaction(connection)

    def _initialize_postgres(self) -> None:
        # Runs once at start-up, so it uses a throwaway connection rather than
        # the reused one. Imports the legacy JSON database only when the
        # PostgreSQL row is empty.
        legacy_data = self._read_json()
        with psycopg.connect(self.database_url, prepare_threshold=None) as connection:
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