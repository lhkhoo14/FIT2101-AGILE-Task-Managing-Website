# John Monash — Technical Guide

This guide is for the person who has to **run, configure, deploy, maintain or
continue developing** the application. It assumes you are comfortable with
Python, a terminal, Git and the basics of web applications.

For the end-user instructions, see the [user guide](user-guide.md).

---

## Contents

1. [Architecture at a glance](#1-architecture-at-a-glance)
2. [Technology stack](#2-technology-stack)
3. [Repository layout](#3-repository-layout)
4. [Running it locally](#4-running-it-locally)
5. [Configuration](#5-configuration)
6. [Data model](#6-data-model)
7. [Backend modules](#7-backend-modules)
8. [API reference](#8-api-reference)
9. [Authorisation model](#9-authorisation-model)
10. [Security model and known limitations](#10-security-model-and-known-limitations)
11. [Email delivery](#11-email-delivery)
12. [Concurrency and persistence rules](#12-concurrency-and-persistence-rules)
13. [Frontend architecture](#13-frontend-architecture)
14. [Build and deploy](#14-build-and-deploy)
15. [Testing](#15-testing)
16. [Maintenance playbook](#16-maintenance-playbook)
17. [Known issues and roadmap](#17-known-issues-and-roadmap)
18. [Glossary](#18-glossary)

---

## 1. Architecture at a glance

```
 Browser
 ┌──────────────────────────────────────────────────────────────┐
 │ src/views/*.html        one page per screen                  │
 │ src/backend/**/*.py     Python running in the browser        │
 │                         (PyScript + Pyodide, WASM)           │
 │      settings.json      maps each module to a bare name      │
 └───────────────────────────────┬──────────────────────────────┘
                                 │ HTTPS, JSON
                                 │ the caller's user_id travels in the
                                 │ payload or query string (see §10)
 ┌───────────────────────────────▼──────────────────────────────┐
 │ FastAPI  (server/main.py)      /api/*  and  /health          │
 │   routes/auth.py  routes/projects.py                         │
 │   routes/sprints.py  routes/activity.py                      │
 │   logic/*        pure functions, no framework                │
 │   database_manager.py, dependencies.py, security.py, mailer  │
 └───────┬───────────────────────────────────────┬──────────────┘
         │ psycopg (pooled)                      │ HTTPS
 ┌───────▼───────────────────────┐      ┌────────▼───────────────┐
 │ PostgreSQL (Supabase / Neon)  │      │ Brevo transactional API │
 │  application_state (1 JSONB)  │      │ verification + reset    │
 │  user_avatars                 │      │ mail                    │
 └───────────────────────────────┘      └────────────────────────┘

 Without DATABASE_URL the API uses a JSON file
 (server/data/server_database.json) instead of PostgreSQL.
```

Two things surprise new maintainers:

- **The frontend is Python, not JavaScript.** Every `*.py` file under
  `src/backend/` is downloaded by the browser and executed by Pyodide when the
  page loads. There is no build step for it beyond copying files.
- **The database is one document.** All users and projects live in a single JSONB
  row that every request reads and rewrites whole. Avatars are the only data kept
  outside it.

---

## 2. Technology stack

| Layer | Used | Notes |
|---|---|---|
| Language | Python 3.12 | The API and the browser code are both Python. |
| Web framework | FastAPI + Uvicorn | Routers mounted under `/api`; `/health` for Render. |
| Validation | Pydantic v2 | Request models per route. |
| Database driver | psycopg 3 (+ psycopg_pool) | Pinned in `server/requirements.txt`; see the deploy note in §14. |
| Database | PostgreSQL 15+ (Supabase/Neon) | One row + one avatar table (§6). |
| Password hashing | bcrypt via `server/security.py` | Long passwords are pre-hashed with SHA-256. |
| Email | Brevo v3 HTTP API (`httpx`) | HTTPS because Render blocks SMTP ports (§11). |
| Frontend runtime | PyScript 2026.7.3 + Pyodide | `settings.json` lists the modules to load. |
| Styling | Hand-written CSS | One file per page plus `base.css`, `layout.css`. |
| Hosting | Render (web service + static site) | Declared in `render.yaml`. |
| Tooling | pyright, script-based test suites | No pytest: see §15. |

---

## 3. Repository layout

```
server/                     the API
  main.py                   app, CORS, /health, router mounting
  database_manager.py       Postgres + JSON fallback, read/update/write, avatars
  dependencies.py           membership/permission checks, preset role rules
  security.py               hash_password / verify_password
  mailer.py                 Brevo sender, returns bool and never raises
  routes/                   auth.py, projects.py, sprints.py, activity.py
  logic/                    sprint_logic.py, contribution_logic.py, membership_logic.py
  data/server_database.json fallback database, also the first import for Postgres
  tests/                    five runnable suites (§15)
  requirements.txt

src/
  views/                    one HTML file per screen (13)
  backend/
    server_data.py          the only module that talks to the API
    settings.py             the account-settings page module
    charts.py               small SVG chart helpers
    constants.py            API base URL, session storage key
    utils/                  auth, layout, topbar, dialog, sidebar_state,
                            project_helpers, project_layout, project_role_helpers,
                            sprint_access
    views/                  one module per page (login, dashboard, sprint-page, …)
  components/               avatar.html, sidebar.html, project-sidebar.html, topbar.html
  styles/                   one stylesheet per page plus shared ones
  assets/                   default avatar, logo

scripts/build_frontend.py   builds dist/ for the static host
settings.json               PyScript module map (file path -> bare module name)
render.yaml                 Render blueprint: API web service + static site
index.html                  landing page that sends you to the login page
docs/                       this guide and the user guide
```

---

## 4. Running it locally

You need Python 3.12 on the PATH and two terminals.

```powershell
# once, from the repository root
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r server\requirements.txt
```

```powershell
# terminal 1 - the API on port 8000
.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --reload --host 127.0.0.1 --port 8000
```

```powershell
# terminal 2 - the frontend on port 5500, from the repository root
python -m http.server 5500
```

Open <http://localhost:5500/src/views/login.html>.

- With no `DATABASE_URL` set, the API stores everything in
  `server/data/server_database.json`. That file is tracked by Git, so treat local
  data as disposable and never commit a personal account into it.
- `src/backend/constants.py` chooses the API address: `127.0.0.1:8000/api` when the
  page is served from `localhost` or `127.0.0.1`, otherwise the deployed Render
  URL. If you serve the frontend from a LAN address (a phone on your network, say)
  it will call the deployed API, not your local one.
- The first page load is slow: Pyodide has to download and start.

**Alternative:** build the static site and serve `dist/` instead —
`python scripts/build_frontend.py`, then serve `dist/` on any port using
`localhost`, so the API address still resolves to your local server.

---


## 5. Configuration

Everything is environment-driven; nothing secret is in the repository.
`.env.example` documents the set.

| Variable | Read by | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | `database_manager.py` | unset | PostgreSQL URI. **Unset means the JSON file fallback is used**, which is what local development and the tests do. |
| `CORS_ORIGINS` | `main.py` | `*` | Comma-separated browser origins allowed to call the API. Set this to the deployed frontend URL in production. |
| `BREVO_API_KEY` | `mailer.py` | unset | Brevo v3 API key. **Unset means nothing is sent** and each message is printed to the log instead. |
| `MAIL_FROM` | `mailer.py` | unset | Sender address, must be verified under *Brevo → Senders*. |
| `MAIL_FROM_NAME` | `mailer.py` | `John Monash` | Display name beside that address. |
| `FRONTEND_URL` | `routes/auth.py` | `http://localhost:5500` | Base URL used to build the confirm-new-email link. |
| `DB_POOL_MIN` / `DB_POOL_MAX` | `database_manager.py` | `2` / `8` | Connection-pool bounds. Keep `MAX` below the database plan's connection limit. |
| `PORT` | Render | — | Injected by Render; `render.yaml` passes it to uvicorn. |

**Reading the configuration in PowerShell** (local, one session):

```powershell
$env:DATABASE_URL = "postgresql://..."
$env:CORS_ORIGINS = "http://localhost:5500"
$env:BREVO_API_KEY = "xkeysib-..."
$env:MAIL_FROM = "you@example.com"
.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --reload --port 8000
```

Never put a key in `src/`, `settings.json` or `render.yaml`. Anything under `src/`
and `dist/` is downloaded by the browser and therefore public.

---

## 6. Data model

### Tables

```sql
application_state (
  state_id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (state_id),
  data     JSONB NOT NULL
)

user_avatars (
  user_id      INTEGER PRIMARY KEY,
  content_type TEXT NOT NULL,
  bytes        BYTEA NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

`application_state` holds exactly one row. Both tables are created on first
start-up by `DatabaseManager._initialize_postgres()`, which also imports
`server/data/server_database.json` if the row is empty. That import happens once;
changing the JSON afterwards does **not** affect a live PostgreSQL database.

Avatars live in their own table because the state document is rewritten whole on
every request, and an image is kilobytes of base64.

### The state document

```jsonc
{
  "next_user_id": 6, "next_project_id": 6,
  "next_backlog_id": 16, "next_sprint_id": 8,
  "users": [ { ...user... } ],
  "projects": { "1": { ...project... } }
}
```

`next_*` counters are never decremented, so ids are never reused. A deleted
account's id is retired for good.

### user

| Field | Meaning |
|---|---|
| `user_id`, `username`, `email`, `password` | Identity. `password` is a bcrypt hash; `email` is stored lower-cased. `username` is unique (case-insensitively) and is what other members search for. |
| `is_verified` | Set by the six-character code. **A missing flag means a legacy account and counts as verified** — see `auth._is_verified`. |
| `verify_code`, `created_at`, `last_email_sent_at` | Verification state; unverified accounts older than 24 h are purged on the next auth request. |
| `failed_attempts`, `lockout_until` | Login throttling. Three failures lock for 30 s; every third failure after that lengthens it. |
| `reset_code`, `reset_code_expires_at`, `reset_attempts`, `last_reset_sent_at` | Password reset: 15 minutes, 5 guesses, 60 s between requests. |
| `pending_email`, `pending_email_token_hash`, `pending_email_expires` | A confirmed-by-link address change, in flight. Only the token's SHA-256 hash is stored. |
| `has_avatar`, `avatar_updated_at` | Whether the bytes are in `user_avatars`, and a cache-busting stamp in **milliseconds**. |
| `projects` | Legacy: the ids this user created. The projects list is computed from project membership, not from this. |

### project

| Field | Meaning |
|---|---|
| `project_id`, `name`, `description`, `status` | `status` is `active` or `completed`. |
| `created_at` | Epoch **milliseconds**, or `null` for a project created before the field existed (the dashboard sorts those as oldest). |
| `creator`, `members`, `contribute` | Lists of user ids. `members` decides access; `contribute` is the legacy list the Members tab reads. |
| `roles` | Role name → list of user ids. One person may appear in several. |
| `role_definitions` | Role name → `{colour, description, permissions[], conflicting_roles[]}`. **This is what the permission checks read.** |
| `backlog` | Product backlog items: `{id, title, tags[], priority, description}`. |
| `sprints` | See below. |
| `history` | Audit trail, newest last, capped at 500 entries (`contribution_logic.HISTORY_LIMIT`). |
| `contributions` | Recomputable per-member totals (`refresh_contributions`). |
| `last_edited_by`, `last_edited_at`, `status_synced_at` | Bookkeeping for the description and automatic sprint completion. |

### sprint

`id` (string), `name`, `details`, `status` (`active` / `ended`), `start_date`,
`end_date` (ISO `YYYY-MM-DD`), `priority` (`high` / `medium` / `low`), `tags[]`,
`members[]`, `created_by`, `created_at`, `ended_at`, and:

```jsonc
"kanban_state": { "backlog": [], "active": [], "review": [], "completed": [] }
```

A sprint is completed automatically once today is past its `end_date`.

### task card

`id` (`"task-<n>"`), `title`, `tags[]`, `description` (≤ 1000 chars),
`priority`, `assignee`, `assignee_id`, `start_date`, `end_date`, `checklist[]`,
`feedback[]`, `work_logs[]`, `done`, `completed_at`.

### history entry

`action`, `message`, `actor`, `actor_id`, `sprint_id`, `sprint_name`, `task_id`,
`task_title`, `from_status`, `to_status`, `timestamp` (display), `recorded_at`
(ISO).

---

## 7. Backend modules

| Module | Responsibility |
|---|---|
| `main.py` | Creates the app, CORS from `CORS_ORIGINS`, mounts the four routers under `/api`, exposes `/health`. |
| `database_manager.py` | Owns persistence. `read()`, `update(mutator)`, `write()`; PostgreSQL through a `psycopg_pool` connection pool, JSON file otherwise. Also the two avatar methods and the schema bootstrap. |
| `dependencies.py` | `verify_project_access`, `verify_project_permission`, `get_verified_project`, `validate_role_assignment`, `SINGLETON_PRESET_ROLES`. |
| `security.py` | `hash_password` / `verify_password` (bcrypt, SHA-256 pre-hash above 72 bytes). |
| `mailer.py` | `send_verification_code`, `send_password_reset_code`, `send_verification_email`. Return `True`/`False`, never raise. |
| `routes/auth.py` | Registration, verification, login, password reset, account settings, avatars, email change, account deletion. |
| `routes/projects.py` | Projects, description, status, members, backlog, the role map and role definitions. |
| `routes/sprints.py` | Sprints, boards, task deletion, moving backlog items in and out. |
| `routes/activity.py` | Change history, contribution figures, work logging. |
| `logic/sprint_logic.py` | Date validation, board diffing, task lookup, tag normalisation, automatic completion. Pure functions. |
| `logic/contribution_logic.py` | Per-member statistics, history append, UTC stamps. Pure functions. |
| `logic/membership_logic.py` | Who may remove whom (`is_sole_creator`, `can_remove_member`, `detach_member`). |

---


## 8. API reference

All routes are under `/api`. Bodies and responses are JSON. Errors use FastAPI's
shape, `{"detail": "message"}`: **422** means a field was invalid, **401** a
wrong credential, **403** "you may not do this", **409** a conflict with the
current state, **429** a cooldown or lockout.

The authoritative client-side contract is `src/backend/server_data.py`; the tables
below list the fields that matter, not every optional one.

### Authentication

| Method and path | Body | Notes |
|---|---|---|
| `POST /login` | `email`, `password` | `200 {status, user_id}`. 401 wrong password (with a remaining-attempts count), 403 unverified, 429 locked. |
| `POST /register` | `email`, `username`, `password` | `201 {status, user_id, message, email_sent}`. Re-registering an unverified address resends a code. |
| `POST /register/check-email` | `email` | `200` if the address is free, `400` if it is taken (case-insensitive). |
| `POST /verify-code` | `email`, `code` | `200` marks the account verified. |
| `POST /resend-code` | `email` | `200 {status, message, email_sent}`; 60-second cooldown. |
| `POST /forgot-password` | `email` | `200 {status, message, email_sent}`; 60-second cooldown. |
| `POST /reset-password` | `email`, `code`, `new_password` | `200`; five wrong codes discard the code. |

### Users, avatars and settings

| Method and path | Body / query | Notes |
|---|---|---|
| `GET /users/{id}` | — | `{user_id, username, profile_photo}`. No email is returned. |
| `GET /users` | `?user_id=` | Every account as `{user_id, username, profile_photo}`. Used to fill pickers; the caller id must exist. |
| `GET /users/{id}/settings` | — | The settings page payload: username, email, pending email, avatar URL. |
| `PATCH /users/{id}/profile` | `username?`, `profile_photo?` | `profile_photo` is a `data:image/…;base64,` URL, or `""` to remove. 409 if the name is taken, 422 if the image is unusable. |
| `GET /users/{id}/avatar` | — | The image bytes with an `ETag`; `304` when the browser already has it. |
| `POST /users/{id}/email-change` | `new_email`, `current_password` | `200 {status, email_sent}`; 401 on a wrong password. Stores only a hash of the token. |
| `POST /users/email-verify` | `token` | `200 {status, email}`; the token *is* the credential here. |
| `POST /users/{id}/password` | `current_password`, `new_password` | `200`; 401 wrong current password, 422 too short, 400 unchanged. |
| `POST /users/{id}/delete` | `password` | `200`; cascades memberships, promotes a new owner, deletes projects left empty. |

### Projects

| Method and path | Body / query | Notes |
|---|---|---|
| `POST /projects` | `user_id`, `name`, `description` | `201 {status, project}`. The creator becomes Project Creator. |
| `GET /users/{id}/projects` | — | A **summary** per project (`project_summary`): id, name, description, status, dates, roles. Boards and tasks are not included. |
| `GET /projects/{id}` | `?user_id=` | The whole project, for a member. |
| `PUT /projects/{id}/description` | `user_id`, `description` | Needs `edit_project`. Returns the new text and its audit fields. |
| `PATCH /projects/{id}/status` | `user_id`, `status` | Needs `edit_project`. `active` ↔ `completed`, in either direction. |
| `DELETE /projects/{id}` | `user_id` | Needs `delete_project`. |
| `GET /projects/{id}/members` | `?user_id=` | `{members, contribute, roles, role_definitions}`. |
| `POST /projects/{id}/members` | `user_id`, `username` | Adds by username into the Employee role. |
| `POST /projects/{id}/members/{member_id}/remove` | `user_id` | Needs `manage_members` and a higher rank than the target. |

### Roles

| Method and path | Body | Notes |
|---|---|---|
| `POST /projects/{id}/roles` | `user_id`, `name`, `colour`, `description?`, `permissions[]`, `conflicting_roles[]` | Needs `manage_roles`. |
| `PUT /projects/{id}/roles/{role}` | same | Needs `manage_roles`. **Presets are refused with 400.** |
| `DELETE /projects/{id}/roles/{role}` | `user_id` | Needs `manage_roles`; presets refused. |
| `POST /projects/{id}/roles/assign` | `user_id`, `target_user_id`, `role_name` | Needs `manage_roles`; enforces single-seat presets and declared conflicts (422). |
| `POST /projects/{id}/roles/{role}/remove` | `user_id`, `target_user_id` | Needs `manage_roles`; the last Project Creator cannot be removed. |
| `GET /projects/{id}/roles/{role}/members` | `?user_id=` | `{status, role_name, members[]}`. |

### Backlog and sprints

| Method and path | Body / query | Notes |
|---|---|---|
| `GET /projects/{id}/backlog` | `?user_id=` | Product backlog items. |
| `POST /projects/{id}/backlog` | `user_id`, `title`, `priority`, `tags[]` (or legacy `tag`), `description?` | `201 item`. Membership is enough today (see §17). |
| `GET /projects/{id}/sprints` | `?user_id=` | Every sprint of the project. |
| `POST /projects/{id}/sprints` | `user_id`, `name`, `details`, `status`, `start_date`, `end_date`, `priority`, `tags[]`, `members[]`, `created_at?` | `201 sprint`. **Needs `manage_sprints`.** |
| `GET /projects/{id}/sprints/{sid}` | `?user_id=` | One sprint. |
| `PATCH /projects/{id}/sprints/{sid}/status` | `user_id`, `status` | `active` or `ended`. Needs `manage_sprints`; an ended sprint cannot be reopened (409). |
| `DELETE /projects/{id}/sprints/{sid}` | `user_id` | Needs `manage_sprints`; ended sprints are refused (409). |
| `GET /projects/{id}/sprints/{sid}/kanban` | `?user_id=` | `{backlog, active, review, completed}`. |
| `GET /projects/{id}/kanban-states` | `?user_id=` | All boards in one request, keyed by sprint id. |
| `PUT /projects/{id}/sprints/{sid}/kanban` | `user_id`, `state` | Replaces the whole board; dropping a card needs `manage_tasks` and completed cards cannot be dropped. |
| `DELETE /projects/{id}/sprints/{sid}/tasks/{tid}` | `user_id` | Needs `manage_tasks`; completed tasks refused. |
| `POST /projects/{id}/sprints/{sid}/backlog` | `user_id`, `backlog_id` | Moves a product-backlog item into the sprint. |
| `POST /projects/{id}/sprints/{sid}/tasks/{tid}/return-to-backlog` | `user_id` | Only from the Sprint Backlog column, sprint members only, and only before work is logged. |
| `GET /projects/{id}/sprints/{sid}/backlog` | `?user_id=` | The board flattened, each item carrying its column. |

### Activity

| Method and path | Body / query | Notes |
|---|---|---|
| `GET /projects/{id}/history` | `?user_id=&limit=` | Newest first; `limit` is capped at 500. |
| `POST /projects/{id}/history` | `user_id`, `action`, `message`, plus optional sprint/task/status fields | Appends one audit entry. |
| `GET /projects/{id}/contributions` | `?user_id=` | `{members[], total_logged_seconds}`; recomputed and stored on read. |
| `POST /projects/{id}/sprints/{sid}/tasks/{tid}/time-log` | `user_id`, `action` (`start` or `stop`) | Opens or closes a work session, then recomputes contributions. |

`GET /health` (outside `/api`) returns `{status: ok}` and exists for Render's health
check.

---


## 9. Authorisation model

Two questions, asked in this order.

**1. Is this person on the project?** `verify_project_access(project, user_id)`
looks in `project["members"]`. Everything except the auth endpoints starts here.

**2. Does their role allow this?** `verify_project_permission(project, user_id,
permission)` collects the roles that list the user and checks
`role_definitions[role]["permissions"]`. One matching role is enough.

### Preset roles and their permissions

| Permission | Project Creator | Scrum Master | Product Owner | Manager | Employee |
|---|:---:|:---:|:---:|:---:|:---:|
| `edit_project` | ✓ | ✓ | ✓ | | |
| `delete_project` | ✓ | | | | |
| `manage_members` | ✓ | ✓ | ✓ | | |
| `manage_roles` | ✓ | ✓ | ✓ | | |
| `assign_roles` | ✓ | ✓ | ✓ | | |
| `manage_sprints` | ✓ | ✓ | ✓ | ✓ | |
| `edit_sprints` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `manage_tasks` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `review_tasks` | ✓ | ✓ | ✓ | ✓ | |

`Project Creator`, `Scrum Master` and `Product Owner` are **single-seat**:
`dependencies.SINGLETON_PRESET_ROLES`, enforced by `validate_role_assignment`.
Which routes need which permission (see the API tables for the endpoints):

| Action | Check |
|---|---|
| Create / update / delete a project | membership, then `delete_project` for the delete |
| Edit description or status | `edit_project` |
| Add or remove members | `manage_members`, plus a rank comparison for removal |
| Manage the role map | `manage_roles` |
| Create, end, delete a sprint | `manage_sprints` |
| Save a board | membership; `manage_tasks` when the save drops a card |
| Delete a task | `manage_tasks` |
| Move a card into Review / Completed, or backwards | `review_tasks` (checked in the page and the board save) |

### Repairing old projects

A project stored before roles existed has `roles: {}` and no `role_definitions`,
which would make every permission check refuse everybody, the creator included.
`projects.ensure_member_fields(project)` rebuilds the five preset keys and their
definitions, puts the creator in `Project Creator` and everyone else in
`Employee`. It runs before any permission check, mutating the copy in hand. A
read-only request therefore repairs only what it returns; the repair becomes
permanent with the next write, which is why `sprints._project_for_write()` applies
the same repairs inside the transaction it is about to save.

---

## 10. Security model and known limitations

**What is in place**

- Passwords are bcrypt hashes (`security.py`), never stored or logged in clear.
- Email verification with a six-character code for every new account.
- Login throttling: three failures lock the account for 30 s, and the lock grows
  with repeated failures.
- Password reset codes expire after 15 minutes and allow five guesses.
- Changing a password, changing an email address or deleting an account all
  require the current password.
- Only a SHA-256 hash of the confirm-new-email token is stored.
- The user endpoints no longer return email addresses, and the project list
  returns a summary rather than whole boards.
- Secrets are environment variables only; nothing sensitive ships to the browser.
- CORS is restricted through `CORS_ORIGINS` (falls back to `*` for local ease).

**The one significant limitation: an id is not a session**

There is no server-side session. The browser stores the signed-in `user_id` in
`sessionStorage` and sends it with every request; the API treats that id as the
caller. In practice this means:

- someone who knows a `user_id` can *claim* it with a direct HTTP call;
- authorization answers "what may this id do", not "who is asking";
- the mitigation is that every *sensitive* action also needs the password, and the
  most revealing endpoints were trimmed.

This is a deployment behind a course project, not a public service, so the risk
was accepted. **If you take the project further, this is the first thing to
change.** The agreed design: a signed bearer token
(`user_id.expiry.token_version`, HMAC with a `SESSION_SECRET`), a `current_user`
dependency, and a per-user `token_version` bumped by password changes so tokens
can be revoked. It touches every route and `server_data.py`, which is why it is a
project of its own rather than a patch.

**Other things to know**

- `PATCH /users/{id}/profile` needs no password, so an id can rename an account or
  change its picture. Cosmetic, but it is the same root cause.
- The verification code has no attempt limit (it expires in 24 hours). The reset
  code does.
- Project ids and user ids are sequential.
- Everything is single-process by design: the connection pool lives in the API
  process, and the JSON fallback cannot be shared between processes (§12).

---

## 11. Email delivery

Two outgoing messages matter.

| When | Contents |
|---|---|
| Registration, and “resend code” | Subject *Your Verification Code*; a six-character code, valid 24 hours. |
| Forgot password | Subject *Password Reset Code*; a six-character code, valid 15 minutes. |
| Email change | Subject *Confirm your new email address*; a link to `FRONTEND_URL/src/views/settings.html?verify_email=<token>`. |

**Why HTTPS and not SMTP.** Render's free web services block outbound SMTP ports
(25, 465, 587). An SMTP client works locally and times out in production. Brevo's
v3 HTTP API is not restricted, so `mailer.py` posts JSON to
`https://api.brevo.com/v3/smtp/email` with `httpx` and a 10-second timeout.

**Behaviour when it is not configured.** With no `BREVO_API_KEY` or `MAIL_FROM`,
`_send()` prints `[DEV] <subject> for <address>` and the message body to the log
and returns `False`. Development and the test suites run this way on purpose:
no code in the repository can send real mail.

**Failures are reported, not raised.** Every sender returns `True` or `False`.
A verification or reset endpoint answers `200` with `{"email_sent": false}` —
the code is stored, but nobody received it. The interface says so instead of
claiming the mail went out. There is no retry or queue: the user presses “send
code” again after the 60-second cooldown.

**Sending happens after the commit.** The code is stored inside
`db_manager.update()`, and `mailer.*` is called only once that returns. Sending
inside the mutator would hold the state row (and every other writer) for the
duration of an HTTPS call, and a failure would roll the registration back.

**Quota.** Brevo's free plan allows 300 messages a day. Unverified accounts are
purged after 24 hours, so a burst of abandoned sign-ups does not accumulate.

---

## 12. Concurrency and persistence rules

These four rules are what keep the single-document database correct. Breaking any
of them produces bugs that only appear under load.

1. **Mutate through `db_manager.update(mutator)`.** The mutator receives the
document and returns a value. On PostgreSQL the row is read `FOR UPDATE` and
committed in the same transaction, so two writers serialise. On the JSON fallback
the read and the write are one step in one process.
2. **Never `read()` and then `write()`.** `write()` replaces the **whole**
document, so a write built from a read taken a moment earlier silently reverts
anything committed in between — including a registration or a failed-login
counter. All mutating project and sprint routes were converted to `update()` for
this reason; the audit trail is in the module docstring of `routes/activity.py`.
3. **A GET must not write.** Repairs are applied to the copy a read returns. A
   read that wrote could clobber a concurrent write.
4. **A mutator that raises is rolled back.** If a change has to survive a failed
   request (a wrong password still has to count towards the lockout), return the
   `HTTPException` from the mutator and let the route raise it after `update()`
   returns — see `auth._raise_saved_failure`.

`read()` and `write()` also exist and are used by read-only endpoints and by the
initial import. The JSON fallback is for one process only: do not start uvicorn
with multiple workers while it is in use.

---


## 13. Frontend architecture

Every page is an HTML file plus a Python module that Pyodide runs in the browser.

```html
<script type="py" config="../../settings.json"
        src="../backend/views/sprint-page.py?v=20261011"></script>
```

`settings.json` maps each file to a **bare module name**:

```json
"files": { "./src/backend/utils/auth.py": "./auth.py" }
```

That is why the modules write `from auth import show_snackbar` instead of a package
path — the browser fetches `auth.py` and registers it under that name. Two
consequences for contributors:

- **Every module you add must be listed in `settings.json`**, or `import` fails at
  run time in the browser while working perfectly in tests.
- Imports of browser-only modules (`js`, `pyodide`, `pyscript`) carry
  `# type: ignore`, because no editor can resolve them. `test_deletions.py`
enforces both rules.

### Page modules and their pages

| Page (`src/views/`) | Module (`src/backend/views/`) |
|---|---|
| `login.html`, `signup.html`, `verify.html`, `forgot-password.html` | `login.py`, `signup.py`, `verify.py`, `forgot_password.py` |
| `dashboard.html` | `dashboard.py` |
| `create-project.html` | `create_project.py` |
| `project-page.html` | `project_page.py` |
| `project-members.html` | `project_members.py` |
| `project-roles.html`, `project-role-details.html` | `project_roles.py`, `project_role_details.py` |
| `sprint-dashboard.html` | `sprint-dashboard.py` |
| `sprint-page.html` | `sprint-page.py` |
| `settings.html` | `../settings.py` |

### Shared modules

| Module | Provides |
|---|---|
| `server_data.py` | `ServerData`, the **only** module that calls the API. Every request goes through it, so it is the place to change the client/server contract. |
| `utils/auth.py` | Field validation, `show_snackbar`, `show_feedback`, `clear_errors`, password masking. |
| `utils/layout.py`, `utils/topbar.py` | The shared shell and the account menu. |
| `utils/project_layout.py` | The project sidebar: active tab, collapse state, Delete Project, nav between project pages. |
| `utils/project_role_helpers.py` | The client's copy of the preset roles, `PRESET_RANK`, `permissions_for_user`, `can_remove_member`. Keep it in step with `routes/projects.PRESET_ROLES`. |
| `utils/sprint_access.py` | Sprint helpers: membership, priority order, tag normalisation, description limit. |
| `utils/dialog.py`, `utils/sidebar_state.py`, `charts.py` | Confirmation dialogs, remembered sidebar state, small SVG charts. |

**Boot pattern.** A page module ends with
`asyncio.ensure_future(init_…)`, which fetches the data, renders, and only then
reveals the controls the caller may use. Hiding a control is presentation only:
the server re-checks every request.

**Caching.** Script and stylesheet tags carry `?v=YYYYMMDD`. Bump the value when
you change a module or stylesheet, or browsers keep the old copy even after a
normal reload.

### Adding a page

1. Add the HTML in `src/views/` (start from an existing page to inherit the shell).
2. Add the module in `src/backend/views/`.
3. Register the module in `settings.json`.
4. Add the `<script type="py" …>` tag with a fresh `?v=` value.
5. Run `server/tests/test_frontend.py` — it serves the build and fails on any
   404 in a page's scripts, links or images — and `test_deletions.py`, which
   checks the client import graph.

---

## 14. Build and deploy

```powershell
python scripts/build_frontend.py     # -> dist/
```

`dist/` is the static site: `index.html`, `settings.json` and `src/`. It is
**gitignored and rebuilt** — never edit it by hand.

`render.yaml` declares both services:

| Service | Type | Build | Start |
|---|---|---|---|
| `fit2101-api` | Python web, `rootDir: server` | `pip install -r requirements.txt` | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| `fit2101-frontend` | Static site | `python scripts/build_frontend.py` | publishes `dist/` |

The API service has `healthCheckPath: /health`, which is why that route exists.

**Deploying**

1. Push to the branch Render tracks (the team's `main`). Both services rebuild.
2. Set the API's environment variables in Render: `DATABASE_URL`, `BREVO_API_KEY`,
   `MAIL_FROM`, `MAIL_FROM_NAME`, `FRONTEND_URL`, and `CORS_ORIGINS` once the
   frontend URL is known.
3. First boot creates `application_state` and `user_avatars`, and imports
   `server/data/server_database.json` if the state row is empty.
4. Check the log: it should reach `Uvicorn running` and pass the health check.

**Deploy checklist**

- `server/requirements.txt` contains every import the API makes at module scope.
  A missing driver does not degrade — the process dies during import. `psycopg`,
  `psycopg-binary` and `psycopg-pool` are pinned there for exactly this reason.
- `DATABASE_URL` uses the provider's **session pooler** URI and ends with
  `?sslmode=require`.
- `FRONTEND_URL` has no trailing slash.
- `CORS_ORIGINS` lists the exact browser origin, scheme included.
- The Brevo sender in `MAIL_FROM` is verified in Brevo, or every send returns 400.

**Free plan.** The API sleeps when idle; the first request afterwards takes a few
seconds while it wakes. Nothing is lost — the database is external.

**Rolling back.** `git revert <commit>` and push, or redeploy the previous commit
from the Render dashboard. The frontend and API deploy from the same commit, so
revert both together: a client that expects a new field will fail against an old
API.

---

## 15. Testing

There is no pytest. Each suite is a script that prints `PASS`/`FAIL` per check and
exits non-zero if anything failed, so it can gate a merge.

```powershell
.venv\Scripts\python.exe server\tests\test_auth.py
.venv\Scripts\python.exe server\tests\test_live_api.py
.venv\Scripts\python.exe server\tests\test_deletions.py
.venv\Scripts\python.exe server\tests\test_mailer.py
.venv\Scripts\python.exe server\tests\test_frontend.py
.venv\Scripts\pyright.exe
```

| Suite | What it covers |
|---|---|
| `test_auth.py` | Registration, verification, login and lockout, password reset, email change, account settings and the user endpoints, against a temporary JSON database. |
| `test_live_api.py` | Starts a real uvicorn server on a free port and drives it over HTTP with the same payloads the browser sends, then checks the server log has no traceback. |
| `test_deletions.py` | In-process TestClient: task/sprint/project/account deletion, every permission rule, plus static checks of the browser modules (imports resolve, no duplicate imports, no undefined calls, no password field is trimmed). |
| `test_mailer.py` | The mailer uses HTTPS not SMTP, reads its key from the environment, never sends when unconfigured, and `render.yaml` / `.env.example` document the settings. |
| `test_frontend.py` | Rebuilds `dist/`, serves it, and fetches every page, asset and `settings.json` module — a 404 anywhere fails the run. |

All suites run against temporary databases and assert that the tracked
`server/data/server_database.json` is unchanged. `test_frontend.py` rewrites
`dist/` as a side effect.

**Adding a check.** Inside a suite:

```python
check("what should be true", condition, detail_shown_on_failure)
```

Keep the detail useful: it is the only output you get when a check fails in CI.

---

## 16. Maintenance playbook

**Rotate the mail key.** New key in Brevo → update `BREVO_API_KEY` in Render →
redeploy. Nothing in the repository changes.

**Rotate the database password.** Update the connection string in the provider,
then `DATABASE_URL` in Render, then redeploy.

**Add a permission.** Add it to `PRESET_ROLES` in `server/routes/projects.py`
where it belongs, and to `ROLE_PERMISSIONS` and `PRESET_ROLES` in
`src/backend/utils/project_role_helpers.py` (the client shows it as a checkbox and
explains it). Then call `verify_project_permission(project, user_id, "new_one")`
in the route, and add a suite check for both the allowed and the refused caller.
Projects stored earlier pick the permission up through `ensure_member_fields`.

**Add a preset role.** Both `PRESET_ROLES` tables, `PRESET_RANK` in
`project_role_helpers.py`, `SINGLETON_PRESET_ROLES` in `dependencies.py` if only
one person may hold it, and this guide's tables.

**Add a field to a stored record.** Write it with a default on write, and read it
with `.get(field, default)` so records stored earlier keep working — that is how
`is_verified`, `created_at`, `status` and `failed_attempts` are handled. If the
default must be a one-off backfill instead, write a short script that loads the
document through `db_manager.update()` and rewrites the field, and run it once
against production.

**Back up.** On Supabase/Neon use the provider's automated backups, or
`pg_dump` the two tables. On the JSON fallback, copy
`server/data/server_database.json`.

**Trim data.** History is capped at 500 entries per project automatically.
Contribution figures are recomputed on read, so they never need repairing. Avatar
rows are keyed by user id and are not deleted with the account; to clean them up,
delete `user_avatars` rows whose `user_id` no longer appears in the state
document.

**Upgrade dependencies.** Bump `server/requirements.txt`, run all five suites and
pyright, then deploy. Keep the three psycopg packages on the same version.

**Debugging.** `/health` tells you the process is up. The uvicorn log shows every
request and any traceback. With no Brevo key, the log also contains the `[DEV]`
mail bodies — including verification and reset codes, which is useful locally and
something to be careful about in production. Reproduce a data problem locally by
copying the state document out of PostgreSQL into
`server/data/server_database.json` and running without `DATABASE_URL`.

---

## 17. Known issues and roadmap

| Item | Impact | Suggested next step |
|---|---|---|
| No server-side sessions (§10) | An id can be claimed; authorization is per-id, not per-person. | Signed bearer token + `token_version`, phased in route by route. |
| `PATCH /users/{id}/profile` needs no password | An id can rename an account or change its picture. | Covered by the session work; or ask for the password. |
| Product backlog creation and “move into sprint” need no permission | Any member can add backlog items or pull them into a sprint. | Decide the rule (probably `manage_tasks` / `manage_sprints`) and add one check each. |
| Time logging is open to any member | Anyone can log hours against anyone's task. | Restrict to the assignee and holders of `manage_tasks`. |
| `POST /projects` accepts any `user_id` | A project can be created owned by somebody else. | Same class as sessions. |
| Verification code has no attempt limit | A 6-character code can be guessed for 24 hours. | Count attempts like the reset code does. |
| History is capped at 500 per project | Old entries are dropped silently. | Archive to a separate table if it matters. |
| No browser-level tests | The Python UI is covered by static checks and manual testing only. | Playwright against the built site. |
| JSON fallback is single-process | Two workers would lose writes. | Only ever run it for local development. |

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **Permission** | A named capability, e.g. `manage_tasks`. The unit authorization is written in. |
| **Role definition** | `{colour, description, permissions[], conflicting_roles[]}` stored per role in `project["role_definitions"]`. |
| **Preset role** | One of the five roles every project has: Project Creator, Scrum Master, Product Owner, Manager, Employee. Cannot be edited or deleted. |
| **Single-seat role** | A preset only one member may hold at a time: Project Creator, Scrum Master, Product Owner. |
| **Conflicting roles** | Two roles that may not be held by the same person; enforced on assignment. |
| **Product backlog** | The project's unscheduled work items (`project["backlog"]`). |
| **Sprint backlog** | The first board column: items planned into a sprint but not started. |
| **Board** | A sprint's `kanban_state`: `backlog`, `active`, `review`, `completed`. |
| **Contribution** | Per-member totals of assigned tasks, completed tasks and logged hours. |
| **Lockout** | Temporary refusal of login after repeated wrong passwords. |
| **`db_manager.update()`** | The only safe way to mutate the state document (§12). |
