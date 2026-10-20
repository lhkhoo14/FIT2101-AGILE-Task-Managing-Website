"""Fake browser modules so PyScript code can be imported by plain pytest.

`pyscript`, `js` and `pyodide` only exist inside the browser. Installing small
stand-ins lets the HTTP client in server_data.py run unmodified: pyfetch is
replaced by a recorder (see FakeFetch) and window.localStorage by a dict.
"""
import sys
import types

import frontend_paths  # noqa: F401  (puts src/backend on sys.path)


class FakeStorage:
    def __init__(self):
        self.data = {}

    def getItem(self, key):
        return self.data.get(key)

    def setItem(self, key, value):
        self.data[key] = value

    def removeItem(self, key):
        self.data.pop(key, None)


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = {} if payload is None else payload

    async def json(self):
        return self._payload


class FakeFetch:
    """Stand-in for pyodide.http.pyfetch that records calls and replays a reply."""

    def __init__(self):
        self.calls = []
        self.response = FakeResponse()
        self.error = None

    def reply(self, status=200, payload=None):
        self.response, self.error = FakeResponse(status, payload), None

    def fail(self, exc=None):
        self.error = exc or RuntimeError("network down")

    async def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    return module


def install():
    """Register the fake modules (idempotent) and return (fetch, window)."""
    if "pyscript" in sys.modules and hasattr(sys.modules["pyscript"], "_is_fake"):
        return sys.modules["pyodide.http"].pyfetch, sys.modules["pyscript"].window

    window = types.SimpleNamespace(
        localStorage=FakeStorage(),
        sessionStorage=FakeStorage(),
        location=types.SimpleNamespace(hostname="localhost", search="", href="http://localhost/"),
    )
    fetch = FakeFetch()
    _module("pyscript", window=window, web=types.SimpleNamespace(page={}),
            document=types.SimpleNamespace(), when=lambda *a, **k: (lambda fn: fn), _is_fake=True)
    _module("js", URLSearchParams=types.SimpleNamespace(new=lambda s: types.SimpleNamespace(get=lambda k: None)))
    _module("pyodide")
    _module("pyodide.http", pyfetch=fetch)
    _module("pyodide.ffi", create_proxy=lambda fn: fn)
    return fetch, window