"""dependencies, main, mailer and the database manager (JSON and PostgreSQL paths)."""
import json
import sys
import types

import pytest
from fastapi import HTTPException

import dependencies as deps
import mailer
from database_manager import DatabaseManager


# ======================== dependencies ======================================
def project():
    return {"members": [1, 2], "roles": {"Project Creator": [1], "Scrum Master": [2], "Employee": []},
            "role_definitions": {"Scrum Master": {"conflicting_roles": ["Manager"]}, "Manager": {"conflicting_roles": []},
                                 "Weird": "not-a-dict"}}


@pytest.mark.unit
def test_project_access():
    p = project()
    assert deps.verify_project_access(p, 1) is p
    with pytest.raises(HTTPException) as missing:
        deps.verify_project_access(None, 1)
    assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as outsider:
        deps.verify_project_access(p, 9)
    assert outsider.value.status_code == 403


@pytest.mark.unit
def test_get_verified_project_reads_the_database(db):
    state = db.read()
    state["projects"]["5"] = {"members": [1]}
    db.write(state)
    assert deps.get_verified_project(5, 1) == {"members": [1]}
    with pytest.raises(HTTPException):
        deps.get_verified_project(6, 1)


@pytest.mark.unit
def test_permission_check_with_odd_definitions():
    p = project()
    p["role_definitions"]["Scrum Master"]["permissions"] = ["x"]
    assert deps.verify_project_permission(p, 2, "x") is p
    with pytest.raises(HTTPException):
        deps.verify_project_permission(p, 1, "x")           # creator role has no definition here
    p["roles"]["Weird"] = [2]
    with pytest.raises(HTTPException):
        deps.verify_project_permission(p, 2, "other")


@pytest.mark.unit
def test_role_assignment_rules():
    p = project()
    deps.validate_role_assignment(p, 1, "Employee")
    with pytest.raises(HTTPException, match="one member"):
        deps.validate_role_assignment(p, 1, "Scrum Master")             # a different person holds it
    deps.validate_role_assignment(p, 2, "Scrum Master")                 # same person: no-op
    with pytest.raises(HTTPException, match="Conflict"):
        deps.validate_role_assignment(p, 2, "Manager")                  # Scrum Master lists Manager as a conflict


@pytest.mark.unit
def test_reverse_direction_conflict():
    p = {"roles": {"A": [1]}, "role_definitions": {"A": {"conflicting_roles": ["B"]}, "B": {}}}
    with pytest.raises(HTTPException, match="Conflict"):
        deps.validate_role_assignment(p, 1, "B")


# ======================== main ==============================================
@pytest.mark.api
def test_health_and_cors(client):
    assert client.get("/health").json() == {"status": "ok"}
    response = client.options("/api/login", headers={"Origin": "http://x.test", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] in ("*", "http://x.test")


@pytest.mark.unit
def test_cors_origins_come_from_the_environment(monkeypatch):
    import importlib
    import main
    monkeypatch.setenv("CORS_ORIGINS", "https://a.test, https://b.test")
    reloaded = importlib.reload(main)
    assert reloaded.cors_origins == ["https://a.test", "https://b.test"]
    monkeypatch.delenv("CORS_ORIGINS")
    assert importlib.reload(main).cors_origins == ["*"]


# ======================== mailer ============================================
@pytest.fixture
def smtp_env(monkeypatch):
    for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.mark.unit
def test_mailer_without_smtp_prints_the_link(smtp_env, capsys):
    assert mailer.send_verification_email("a@x.com", "http://link") is False
    assert "http://link" in capsys.readouterr().out


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port, self.calls, self.fail = host, port, [], False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("tls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, message):
        if self.fail:
            raise OSError("boom")
        self.calls.append(("send", message["To"], message["From"]))


# ======================== database manager (JSON) ===========================
@pytest.fixture
def manager(tmp_path):
    return DatabaseManager(db_path=str(tmp_path / "nested" / "db.json"), database_url=None)


@pytest.mark.unit
def test_json_read_defaults_and_corruption(manager):
    assert manager.read()["projects"] == {} and manager.read()["next_user_id"] == 1      # file missing
    with open(manager.db_path, "w") as handle:
        handle.write("{not json")
    assert manager.read()["users"] == []                                                  # corrupt file
    with open(manager.db_path, "w") as handle:
        handle.write("[1, 2]")
    assert manager.read()["users"] == []                                                  # wrong shape
    with open(manager.db_path, "w") as handle:
        json.dump({"users": [{"user_id": 1, "email": "A@x.com"}]}, handle)
    data = manager.read()
    assert data["next_project_id"] == 1 and data["users"][0]["user_id"] == 1             # missing keys filled in


@pytest.mark.unit
def test_json_update_and_lookups(manager):
    manager.write(manager._default_structure())
    result = manager.update(lambda data: data["users"].append({"user_id": 4, "email": "Bob@X.com", "username": "bob"}) or "done")
    assert result == "done"
    assert manager.find_user_by_email("bob@x.com")["user_id"] == 4
    assert manager.find_user_by_id(4)["username"] == "bob"
    assert manager.find_user_by_email("none@x.com") is None and manager.find_user_by_id(9) is None


@pytest.mark.unit
def test_json_avatars(manager):
    assert manager.get_user_avatar(1) is None
    manager.save_user_avatar(1, "image/png", b"bytes")
    assert manager.get_user_avatar(1) == ("image/png", b"bytes")
    manager.save_user_avatar(1, "image/jpeg", b"new")
    assert manager.get_user_avatar(1) == ("image/jpeg", b"new")
    manager.delete_user_avatar(1)
    assert manager.get_user_avatar(1) is None
    manager.delete_user_avatar(1)                                   # deleting nothing is fine
    state = manager.read()
    state["avatars"] = {"2": {"content_type": "image/png", "data": "!!not base64"}}
    manager.write(state)
    assert manager.get_user_avatar(2) is None


@pytest.mark.unit
def test_connection_helpers_without_a_url(manager):
    with pytest.raises(RuntimeError):
        manager._connection()
    manager._initialize_postgres()                                  # no URL: returns quietly
    manager._return_connection(FakeConnection())                    # no pool: closes the connection
    broken = FakeConnection(close_error=True)
    manager._return_connection(broken)                              # close errors are swallowed
    manager._discard_connection(broken)


# ======================== database manager (PostgreSQL, faked) ==============
class FakeResult:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=None, fail=False, close_error=False, rollback_error=False):
        self.row, self.fail, self.close_error, self.rollback_error = row, fail, close_error, rollback_error
        self.statements, self.committed, self.closed, self.rolled_back = [], False, False, False

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError("db down")
        self.statements.append((" ".join(sql.split()), params))
        return FakeResult(self.row)

    def commit(self):
        self.committed = True

    def rollback(self):
        if self.rollback_error:
            raise RuntimeError("cannot roll back")
        self.rolled_back = True

    def close(self):
        if self.close_error:
            raise RuntimeError("cannot close")
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePool:
    def __init__(self, url, **kwargs):
        self.url, self.kwargs, self.conn, self.returned, self.put_error = url, kwargs, None, [], False
        FakePool.last = self

    def open(self):
        self.opened = True

    def wait(self, timeout):
        self.waited = timeout

    def getconn(self):
        return self.conn

    def putconn(self, connection):
        if self.put_error:
            raise RuntimeError("pool closed")
        self.returned.append(connection)


@pytest.fixture
def pg(monkeypatch, tmp_path):
    """A DatabaseManager wired to fake psycopg objects. Returns (manager, connection)."""
    connection = FakeConnection()
    monkeypatch.setitem(sys.modules, "psycopg_pool", types.SimpleNamespace(ConnectionPool=FakePool))
    monkeypatch.setattr("database_manager.psycopg", types.SimpleNamespace(connect=lambda url, **kw: connection))
    manager = DatabaseManager(db_path=str(tmp_path / "legacy.json"), database_url="postgresql://fake")
    FakePool.last = None
    manager._pool = None
    return manager, connection


@pytest.mark.unit
def test_postgres_startup_creates_tables_and_imports_legacy_data(pg):
    manager, connection = pg
    statements = " ".join(sql for sql, _ in connection.statements)
    assert "CREATE TABLE IF NOT EXISTS application_state" in statements and "user_avatars" in statements
    assert "ON CONFLICT (state_id) DO NOTHING" in statements


@pytest.mark.unit
def test_postgres_read_write_update(pg):
    manager, _ = pg
    conn = FakeConnection(row=({"users": [1]},))
    pool = FakePool("x")
    pool.conn = conn
    manager._pool = pool
    assert manager.read() == {"users": [1]} and conn.rolled_back and pool.returned == [conn]

    conn.row = None
    assert manager.read()["projects"] == {}                       # empty table: default structure

    manager.write({"a": 1})
    assert conn.committed and json.loads(conn.statements[-1][1][0]) == {"a": 1}

    conn.row = ({"count": 1},)
    assert manager.update(lambda data: data.update(count=2) or "ok") == "ok"
    assert json.loads(conn.statements[-1][1][0]) == {"count": 2}
    conn.row = None
    manager.update(lambda data: None)                              # no stored row yet


@pytest.mark.unit
def test_postgres_failures_discard_the_connection(pg):
    manager, _ = pg
    conn = FakeConnection(fail=True)
    pool = FakePool("x")
    pool.conn = conn
    manager._pool = pool
    for action in (manager.read, lambda: manager.write({}), lambda: manager.update(lambda d: None),
                   lambda: manager.save_user_avatar(1, "image/png", b"x"), lambda: manager.get_user_avatar(1),
                   lambda: manager.delete_user_avatar(1)):
        conn.closed = False
        with pytest.raises(RuntimeError):
            action()
        assert conn.closed and conn not in pool.returned


@pytest.mark.unit
def test_postgres_avatars(pg):
    manager, _ = pg
    conn = FakeConnection(row=("image/png", b"png-bytes"))
    pool = FakePool("x")
    pool.conn = conn
    manager._pool = pool
    assert manager.get_user_avatar(3) == ("image/png", b"png-bytes")
    conn.row = None
    assert manager.get_user_avatar(3) is None
    manager.save_user_avatar(3, "image/png", b"b")
    manager.delete_user_avatar(3)
    sql = " ".join(statement for statement, _ in conn.statements)
    assert "INSERT INTO user_avatars" in sql and "DELETE FROM user_avatars" in sql


@pytest.mark.unit
def test_postgres_pool_creation_and_return_fallbacks(pg):
    manager, _ = pg
    conn = FakeConnection()
    FakePool.conn_for_new = conn
    original_getconn = FakePool.getconn
    FakePool.getconn = lambda self: conn
    try:
        assert manager._connection() is conn
        pool = FakePool.last
        assert pool.kwargs["min_size"] == manager.pool_min_size and pool.kwargs["kwargs"] == {"prepare_threshold": None}
        assert pool.opened and pool.waited == 10 and manager._connection() is conn
        pool.put_error = True
        manager._return_connection(conn)                          # pool refuses: connection is closed instead
        assert conn.closed
        manager._end_transaction(FakeConnection(rollback_error=True))   # never raises
    finally:
        FakePool.getconn = original_getconn