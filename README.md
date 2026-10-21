# MA_Wednesday10am_Team2

FIT2101 S2 2026 group repository.

## Team

Add your team members and roles here.

- Chan Chee Wei (34073981) - Developer
- Loh Ken Yit (35731958) - Deputy Scrum Master, Developer
- Agasti Ngoh Cheng Che (36791407) - Product Owner, Developer
- Lye Wei Ho (36286761) - Scrum Master, Developer
- Izaan (36784478) - Secretary, Developer
- Khoo Lip Hong (36391948) - Developer

## Documentation

Two guides accompany the application:

- **[User guide](docs/user-guide.md)** - for the people who use the product:
  creating an account, running a project, roles and permissions, sprints and the
  Kanban board, day-to-day tasks, account settings and troubleshooting.
- **[Technical guide](docs/technical-guide.md)** - for whoever has to run, deploy,
  maintain or continue developing it: architecture, configuration, data model,
  API reference, authorisation rules, testing, deployment and a maintenance
  playbook, plus the known limitations of the current design.

Each directory is described in more depth in the technical guide's
*Repository layout* and *Backend modules* sections.

## Getting Started

1. Clone this repository.
2. Create a branch for your work.
3. Commit regularly with clear messages.
4. Open a merge request when your work is ready for review.

## Running the application locally

The login page needs both the static frontend and the FastAPI backend running.
Run these commands from the repository root. Create a virtual environment if
you do not already have one:

```powershell
python -m venv .venv
```

Install the backend dependencies using the virtual environment's Python:

```powershell
cd server
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start the API in one terminal (no activation required):

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --reload --host 127.0.0.1 --port 8000
```
Then you can either:
Right-click `index.html` in the file directory and Click Open with [Live Server]

Or:
Start the frontend in a second terminal:

```powershell
python -m http.server 5500
```

Open `http://localhost:5500/src/views/login.html`. Keep both terminals running
while using the application. The API listens on port 8000; the frontend uses
port 5500.

## Deploying to Render

The repository includes `render.yaml`, which creates two Render resources:

- `fit2101-api`: FastAPI web service
- `fit2101-frontend`: static frontend site

The API is explicitly configured with Render's `free` web-service plan. It may
sleep when inactive, but it does not require the paid $7 plan. Supabase stores
the persistent database separately.

To deploy, push this repository to GitHub and choose **New > Blueprint** in
Render. Select the GitHub repository and apply the Blueprint. During setup,
provide `DATABASE_URL` using a connection string from Neon, Supabase, or
another PostgreSQL provider. The first API startup creates the PostgreSQL table
and imports `server/data/server_database.json` if the table is empty.

After Render creates the frontend, optionally add `CORS_ORIGINS` to the API
service using the actual frontend URL, for example
`https://fit2101-frontend-fiie.onrender.com`. It is intentionally not requested
during initial Blueprint setup because that URL does not exist yet. Until it is
set, the API uses its development-friendly wildcard CORS default.

The frontend build copies only the public application files into `dist`; the
server database and backend-only files are not published by the static site.

## Using Supabase PostgreSQL

Supabase is used here as the PostgreSQL database only. The FastAPI server still
owns the API and authentication flow. Create a Supabase project, then open
**Project Settings > Database > Connection string** and copy the **Session
pooler** URI. Put it in `DATABASE_URL`; do not commit the real password.

For local PowerShell development:

```powershell
$env:DATABASE_URL = "postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-REGION.pooler.supabase.com:5432/postgres?sslmode=require"
$env:CORS_ORIGINS = "http://localhost:5500"
.\.venv\Scripts\python.exe -m uvicorn main:app --app-dir server --reload --host 127.0.0.1 --port 8000
```

For Render, paste the same Supabase URI into the API service's `DATABASE_URL`
environment variable and set `CORS_ORIGINS` to the deployed frontend URL. On
the first connection, the API creates its `application_state` table and imports
the legacy JSON database if that table is empty.

## Repository Structure

The application has three parts: a FastAPI backend under `server/`, a browser
frontend written in Python under `src/`, and the small scripts that build and
configure them.

```
server/                        the FastAPI backend
├── main.py                    app, CORS, /health, router mounting
├── database_manager.py        PostgreSQL + JSON fallback, read/update/write, avatars
├── dependencies.py            membership and permission checks
├── security.py                password hashing (bcrypt)
├── mailer.py                  Brevo (HTTPS) mail sender
├── routes/                    auth.py, projects.py, sprints.py, activity.py
├── logic/                     sprint_logic.py, contribution_logic.py, membership_logic.py
├── data/server_database.json  the JSON fallback database
├── tests/                     test_auth.py, test_live_api.py, test_deletions.py,
│                              test_mailer.py, test_frontend.py
└── requirements.txt

src/
├── views/                     one HTML page per screen (13 files)
├── backend/
│   ├── server_data.py         the only module that calls the API
│   ├── settings.py            the account-settings page
│   ├── constants.py           API base URL, session storage key
│   ├── charts.py              small SVG chart helpers
│   ├── utils/                 auth, layout, topbar, dialog, sidebar_state,
│   │                          project_helpers, project_layout,
│   │                          project_role_helpers, sprint_access
│   └── views/                 one module per page (login, dashboard,
│                              project_page, sprint-page, ...)
├── components/                avatar, sidebar, project-sidebar and topbar partials
├── styles/                    one stylesheet per page plus the shared ones
└── assets/                    default avatar, logo

docs/                          user-guide.md, technical-guide.md
scripts/build_frontend.py      builds dist/ for the static site
settings.json                  PyScript module map (file path -> module name)
render.yaml                    Render blueprint: API web service + static site
index.html                     landing page that forwards to the login page
pyrightconfig.json             type-checker paths for the browser modules
.env.example                   every environment variable, documented
```

Nothing under `server/` is published to the browser: `scripts/build_frontend.py`
copies only `index.html`, `settings.json` and `src/` into `dist/`. The browser
modules import each other by bare name (`from auth import ...`), which is why
every one of them is registered in `settings.json`.

## Notes

Keep your project work, documentation, setup instructions, and relevant artefacts in this repository.
Do not share this repository outside your group and the teaching team.
