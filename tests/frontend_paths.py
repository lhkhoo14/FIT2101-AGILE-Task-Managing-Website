"""Shared locations for the frontend (src/) tests.

The browser code under src/backend/ is loaded by PyScript, so most of it cannot be
imported in plain Python (it needs `pyscript` and `js`). The tests therefore either
import the pure modules directly (sprint_access, charts) or pull individual
functions out with helpers.load_functions.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "src" / "backend"
UTILS = BACKEND / "utils"
VIEWS = BACKEND / "views"

# Pure modules (no pyscript imports) can be imported by name.
for folder in (BACKEND, UTILS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))