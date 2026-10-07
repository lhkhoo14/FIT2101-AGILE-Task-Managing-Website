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
        # A small shared connection pool. Sized for a single Render web instance:
        # enough to serve the frontend's parallel fetches without opening a
        # connection per request, small enough to stay well inside Supabase's
        # connection limits.
        self.pool_min_size = int(os.getenv("DB_POOL_MIN", "2"))
        self.pool_max_size = int(os.getenv("DB_POOL_MAX", "8"))
        self._pool = None
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
        """Borrow a connection from the pool, opening one if the pool is empty.

        CHANGE: this used to cache one connection per thread (threading.local),
        which meant N simultaneous requests each paid a full TCP + TLS handshake
        to Supabase. The frontend fires several fetches at once, so the first
        page load opened one connection per in-flight request. That showed up as
        a slow /users request (~1s) alongside fast ones. A shared bounded pool
        opens a small number of connections once and reuses them.
        """
        if self._pool is None:
            # Imported lazily so the JSON fallback never needs the pool package.
            from psycopg_pool import ConnectionPool

            # Supabase's transaction pooler can hand a connection to a different
            # transaction, so prepared statements are disabled for pooled URLs.
            self._pool = ConnectionPool(
                self.database_url,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                kwargs={"prepare_threshold": None},
                open=False,
            )
            self._pool.open()
            self._pool.wait(timeout=10)
        return self._pool.getconn()

    def _return_connection(self, connection) -> None:
        """Hand a connection back to the pool, dropping it if it looks broken."""
        if self._pool is not None:
            try:
                self._pool.putconn(connection)
                return
            except Exception:
                pass
        try:
            connection.close()
        except Exception:
            pass

    def _discard_connection(self, connection) -> None:
        """Throw away a connection that raised, so it is not reused."""
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
            pass

    def read(self) -> Dict[str, Any]:
        if not self.database_url:
            return self._read_json()

        connection = self._connection()
        broken = False
        try:
            row = connection.execute(
                "SELECT data FROM application_state WHERE state_id = TRUE"
            ).fetchone()
        except Exception:
            broken = True
            raise
        finally:
            # CHANGE: end the transaction, then hand the connection back so the
            # next request reuses it. A connection that raised is discarded.
            self._end_transaction(connection)
            if broken:
                self._discard_connection(connection)
            else:
                self._return_connection(connection)

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
        broken = False
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
            broken = True
            raise
        finally:
            if broken:
                self._discard_connection(connection)
            else:
                self._return_connection(connection)

    def update(self, mutator: Callable[[Dict[str, Any]], T]) -> T:
        """Read, mutate, and save the state atomically when PostgreSQL is active."""
        if not self.database_url:
            data = self._read_json()
            result = mutator(data)
            self.write(data)
            return result

        connection = self._connection()
        broken = False
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
            broken = True
            raise
        finally:
            if broken:
                self._discard_connection(connection)
            else:
                self._return_connection(connection)

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