import base64
import json
import os
import threading
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

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
        if not self.database_url:
            # Unreachable from read()/write()/update(), which take the JSON path
            # when no URL is configured. Raising keeps the pool from being handed
            # None, and says what is actually wrong if a caller ever gets here.
            raise RuntimeError("The PostgreSQL connection pool needs DATABASE_URL to be set.")
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

    # --- Profile pictures -----------------------------------------------
    # Stored apart from the state document (see _initialize_postgres). The JSON
    # fallback keeps the same bytes base64-encoded under "avatars", so local runs
    # and the test suites behave the way PostgreSQL does.
    def save_user_avatar(self, user_id: int, content_type: str, data: bytes) -> None:
        """Store one user's profile picture, replacing any previous one."""
        if not self.database_url:
            encoded = base64.b64encode(data).decode("ascii")

            def mutate(db: Dict[str, Any]) -> None:
                db.setdefault("avatars", {})[str(user_id)] = {
                    "content_type": content_type,
                    "data": encoded,
                }

            self.update(mutate)
            return

        connection = self._connection()
        broken = False
        try:
            connection.execute(
                """
                INSERT INTO user_avatars (user_id, content_type, bytes, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (user_id) DO UPDATE
                    SET content_type = EXCLUDED.content_type,
                        bytes = EXCLUDED.bytes,
                        updated_at = now()
                """,
                (user_id, content_type, data),
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

    def get_user_avatar(self, user_id: int) -> Optional[Tuple[str, bytes]]:
        """(content type, bytes) for a user's picture, or None when there is none."""
        if not self.database_url:
            entry = (self._read_json().get("avatars") or {}).get(str(user_id))
            if not entry:
                return None
            try:
                return str(entry["content_type"]), base64.b64decode(entry["data"])
            except Exception:
                return None

        connection = self._connection()
        broken = False
        try:
            row = connection.execute(
                "SELECT content_type, bytes FROM user_avatars WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        except Exception:
            broken = True
            raise
        finally:
            self._end_transaction(connection)
            if broken:
                self._discard_connection(connection)
            else:
                self._return_connection(connection)

        if not row:
            return None
        return str(row[0]), bytes(row[1])

    def delete_user_avatar(self, user_id: int) -> None:
        """Forget a user's picture (the account keeps its default avatar)."""
        if not self.database_url:
            def mutate(db: Dict[str, Any]) -> None:
                (db.get("avatars") or {}).pop(str(user_id), None)

            self.update(mutate)
            return

        connection = self._connection()
        broken = False
        try:
            connection.execute("DELETE FROM user_avatars WHERE user_id = %s", (user_id,))
            connection.commit()
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
        if not self.database_url:
            # __init__ only calls this with a URL set; returning here keeps the
            # method safe to call directly and makes it obvious to a reader (and
            # a type checker) that psycopg.connect is never handed None.
            return
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
            # Profile pictures live beside the state document, not inside it: an
            # image is a few kilobytes, and the document below is read and
            # rewritten whole on every request.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_avatars (
                    user_id INTEGER PRIMARY KEY,
                    content_type TEXT NOT NULL,
                    bytes BYTEA NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
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