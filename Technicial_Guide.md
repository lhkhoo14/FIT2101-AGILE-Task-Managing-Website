# Technical Guide

For developers who set up, run, test or extend the project.

## 1. Architecture

```
Browser (PyScript)                         Server (FastAPI)
src/views/*.html  --loads-->  src/backend/**/*.py     server/main.py
                                 |                       server/routes/*
                                 | HTTPS (JSON)          server/logic/*
                                 v                       server/dependencies.py
                  server_data.py (ServerData) ---------> server/database_manager.py
                                                          |-- PostgreSQL (DATABASE_URL set)
                                                          '-- JSON file (fallback)
```

- **Frontend:** plain HTML/CSS pages whose behaviour is written in Python and run in the browser by [PyScript](https://pyscript.net). There is no JavaScript build step.
- **Backend:** a FastAPI application. All business rules and permission checks are enforced here; the UI only hides controls the user may not use.
- **Storage:** PostgreSQL through `psycopg` when the `DATABASE_URL` environment variable is set, otherwise a JSON file at `server/data/server_database.json`.

## 2. Repository layout

| Path | Purpose |
|---|---|
| `src/views/*.html` | One page each: login, signup, dashboard, project page, members, roles, sprint dashboard, sprint page, settings |
| `src/components/` | Shared HTML fragments (top bar, sidebars, avatar) |
| `src/styles/` | CSS, one file per page plus `base`, `layout`, `topbar`, `snackbar` |
| `src/backend/views/` | Page logic (`dashboard.py`, `sprint-page.py`, `sprint-dashboard.py`, `project_members.py`, ...) |
| `src/backend/utils/` | Shared browser helpers: `auth`, `dialog`, `layout`, `topbar`, `sidebar_state`, `project_role_helpers`, `sprint_access` |
| `src/backend/server_data.py` | `ServerData`: the only place the browser talks to the API |
| `src/backend/charts.py` | Burndown and pie chart SVG generation (pure Python) |
| `src/backend/constants.py` | API URL (local when served from `localhost`, hosted otherwise) and session key |
| `server/` | FastAPI app, routes, business logic, database layer |
| `tests/` | pytest suite (backend API/logic tests and frontend unit tests) |
| `settings.json` | PyScript file map (see below) |

### How PyScript finds modules
Each HTML page loads its Python with `<script type="py" config="../../settings.json" src="...">`. `settings.json` lists the files PyScript must copy into its virtual filesystem and **flattens the names**, for example `"./src/backend/views/sprint-page.py": "./sprint-page.py"`. This is why Python files import each other by bare name (`from server_data import ServerData`). **A new `.py` file must be added to `settings.json` or the page will fail to import it.** A page script that is empty (0 bytes) breaks the whole page, so check file sizes after a merge.

## 3. Setup and running

Prerequisites: Python 3.11+ and Git. Commands below use Windows paths; on macOS/Linux use `.venv/bin/python` and `/`.

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
cd server
..\.venv\Scripts\python.exe -m uvicorn main:app --reload   # API on http://127.0.0.1:8000
```

The server must be started from inside `server/` because its modules import each other by bare name (`from database_manager import db_manager`).

Serve the front end from the repository root with any static server (for example `python -m http.server 5500`) and open `src/views/login.html`. When the page is served from `localhost` or `127.0.0.1` the client calls `http://127.0.0.1:8000/api`; otherwise it calls the hosted API (`constants.py`).

Environment variables:

| Variable | Effect |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string. When absent the server uses the JSON file. |

Common error: `ModuleNotFoundError: No module named 'psycopg'` means the requirements were not installed into the interpreter that runs uvicorn. Run the `pip install` line above with that same interpreter.

## 4. Permissions model

- A project stores `roles` (role name to list of user ids) and `role_definitions` (role name to `colour`, `description`, `permissions`, `conflicting_roles`).
- Permissions: `manage_members`, `manage_roles`, `assign_roles`, `manage_sprints`, `edit_sprints`, `manage_tasks`, `review_tasks`, `edit_project`, `delete_project`.
- Preset roles (`PRESET_ROLES` in `project_role_helpers.py`): Project Creator, Scrum Master, Product Owner, Manager, Employee. The first three are singletons and are added to every sprint (`LEADERSHIP_ROLES`).
- `permissions_for_user(project, user_id)` returns the union of permissions of every role the user holds, custom roles included. The sprint page loads this once and checks it, for example `"review_tasks" in _permissions`.
- Rank: `PRESET_RANK` orders preset roles; custom roles rank lowest and are compared by permission sets (`can_remove_member`).
- **The server re-checks every permission on every request** (`server/dependencies.py`, `verify_project_permission`). Client-side checks only decide which buttons to show.
- Sprint access is separate from roles: `is_sprint_member(sprint, user_id)`. A legacy sprint with no `members` key is open to everyone; a sprint with a members list (even empty) is restricted.

## 5. API reference

All routes are under `/api` and are called through `ServerData`. A signed-in user's id is sent as `user_id` (query string for GET, body for writes).

| Area | Method and path |
|---|---|
| Auth | `POST /register`, `POST /login` |
| Users | `GET /users`, `GET /users/{id}`, `GET /users/{id}/settings`, `PATCH /users/{id}/profile`, `POST /users/{id}/email-change`, `POST /users/email-verify`, `POST /users/{id}/password`, `POST /users/{id}/delete` |
| Projects | `POST /projects`, `GET /users/{id}/projects`, `GET /projects/{pid}`, `PATCH /projects/{pid}/status`, `DELETE /projects/{pid}` |
| Members | `GET` / `POST /projects/{pid}/members`, `POST /projects/{pid}/members/{mid}/remove` |
| Roles | `POST /projects/{pid}/roles`, `PUT` / `DELETE /projects/{pid}/roles/{name}`, `GET /projects/{pid}/roles/{name}/members`, `POST /projects/{pid}/roles/assign`, `POST /projects/{pid}/roles/{name}/remove` |
| Backlog | `GET` / `POST /projects/{pid}/backlog` |
| Sprints | `GET` / `POST /projects/{pid}/sprints`, `DELETE /projects/{pid}/sprints/{sid}`, `PATCH .../status`, `GET` / `POST .../backlog` |
| Board | `GET` / `PUT /projects/{pid}/sprints/{sid}/kanban`, `GET /projects/{pid}/kanban-states` |
| Tasks | `DELETE .../tasks/{tid}`, `POST .../tasks/{tid}/return-to-backlog`, `POST .../tasks/{tid}/time-log` |
| Reporting | `GET /projects/{pid}/history`, `POST /projects/{pid}/history`, `GET /projects/{pid}/contributions` |

Errors are returned as `{"detail": "..."}` with an HTTP status. `ServerData` turns them into `(success, message)` tuples, empty lists or `None`, and never raises to the page.

## 6. Key front-end patterns

- **Handlers** are registered with `@when("click", "#id")`. Typical flow: find the element, validate, change state, persist through `ServerData`, re-render.
- **Kanban state** lives in `_kanban_state` on the sprint page and is saved as a whole with `update_kanban_state`.
- **Dashboard sorting/filtering** (`dashboard.py`): projects are fetched once into `loaded_projects`; `render_projects()` filters (search text and `status_filter`) then sorts with `sort_projects()` and redraws the grid, so no extra request or reload is needed.
- **Sidebar collapse** is stored in `sessionStorage` by `sidebar_state.py`.
- Pure logic (`sprint_access.py`, `charts.py`) imports no browser modules so it can be unit-tested directly.

## 7. Testing

```bash
pip install pytest pytest-cov
python -m pytest                 # runs everything and prints the coverage table
```

`pytest.ini` puts the repository root and `server/` on the import path and turns coverage on; `.coveragerc` decides which files are measured.

| Test file | What it covers |
|---|---|
| `test_server_auth.py` | Register, login and lockout messages, profile, avatar upload/serve, email change and verification, password change, account deletion |
| `test_server_projects.py` | Projects, members, backlog, custom roles, role assignment rules |
| `test_server_sprints.py` | Sprint create/list/status, kanban save and validation, task deletion, backlog to sprint and back |
| `test_server_activity.py` | Change history, contribution statistics, start/stop work sessions |
| `test_server_logic.py` | Pure rules in `sprint_logic`, `contribution_logic`, `membership_logic` |
| `test_server_infrastructure.py` | Permission helpers, health/CORS, e-mail sending (SMTP faked), database manager on JSON and on PostgreSQL (psycopg faked) |
| older API/logic files | The first suite written for the project (`test_projects_api.py`, `test_security.py`, ...) |
| `test_server_data.py` | Browser API client with `pyfetch` replaced by a recorder |
| `test_sprint_access.py`, `test_charts.py`, `test_project_role_helpers.py` | Pure frontend modules |
| `test_dashboard_logic.py`, `test_sprint_page_logic.py`, `test_view_helpers.py` | Logic functions pulled out of the page scripts |

### How the tests are isolated
- `conftest.py` redirects **both** copies of `db_manager` to a temporary JSON file (the app imports `database_manager`, the tests import `server.database_manager`; these are two module objects). Without that the app would read and write the real `server/data/server_database.json`.
- `reset_database` empties the database before every test. `seed_factory` inserts hand-written records in the shape the server stores them (projects keyed by id).
- `api_helpers.py` builds realistic data through the public API (`register`, `create_project`, `create_sprint`, ...).
- Frontend tests use `frontend_stubs.py` (fake `pyscript`, `js`, `pyodide`) and `helpers.load_functions()` (extracts named functions from a PyScript file with `ast`).
- Slow bcrypt hashing dominates the run time (about a minute); the tests themselves are quick.

### What coverage measures
Coverage is measured on `server/` and on the client modules that can run outside a browser. The following browser-only modules are excluded in `.coveragerc` because they only build and wire DOM elements through PyScript and cannot execute under pytest: everything in `src/backend/views/`, `settings.py`, and `utils/` `auth`, `dialog`, `layout`, `project_layout`, `project_helpers`, `sidebar_state`, `topbar`. Their decision logic has been moved into tested modules where possible and the rest is checked with the manual checklist below. Report the number together with this exclusion: the suite reaches about 99% on the measured code and about 53% if the excluded UI modules were counted.

### Known defects the tests document
- **Login lockout is not saved** (`routes/auth.py`): `login()` raises inside `db_manager.update()`, so the failed-attempt counter and `lockout_until` are discarded and an account never actually locks. `test_repeated_failures_really_lock_the_account` is marked `xfail(strict=True)`; when the bug is fixed the test starts passing and pytest will tell you to remove the marker.
- **Role edits are only partly protected** (`routes/projects.py`): `update_project_role` blocks editing "Project Creator", "Project Manager" and "Project Member", but deleting is blocked for all five presets. Scrum Master, Product Owner, Manager and Employee can be edited through the API.

### Manual regression checklist
1. Register, log in, log out.
2. Create a project; filter by Active/Completed; search; all four sort options.
3. End a project; it moves to Completed.
4. Create a custom role with `review_tasks`; assign it; confirm that member can post feedback and move cards backwards.
5. Create a sprint, add a task from the backlog, move it to Review, then (as a reviewer) to Completed.
6. Check the burndown chart and effort breakdown.
7. Delete a task, a sprint, a project.
8. Change the display name and password; delete a test account.

## 8. Contributing

1. Branch from `main`; keep branches small and short-lived.
2. Pull the latest `main` into your branch and run the app before opening a pull request.
3. Open a pull request; a teammate must review it. Do not merge into `main` from your own machine.
4. Tell the team chat before any merge or revert.
5. After a merge, confirm no page script is empty and that `settings.json` still lists every file.
6. Run `python -m pytest` before pushing. It must pass.

## 9. Known limitations
- The browser downloads the Python runtime on first load, so the first page view is slow.
- UI permission checks are advisory only; the server is the source of truth.
- Data stored in the JSON fallback is for development; use PostgreSQL for shared deployments.