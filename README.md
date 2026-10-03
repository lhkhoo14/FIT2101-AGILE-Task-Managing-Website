# MA_Wednesday10am_Team2

FIT2101 S2 2026 group repository.

## Team

Add your team members and roles here.

Chan Chee Wei (34073981) - Developer
Loh Ken Yit (35731958) - Deputy Scrum Master, Developer
Agasti Ngoh Cheng Che (36791407) Product Owner, Developer
Lye Wei Ho (36286761) Scrum Master, Developer
Izaan (36784478) secretary, Developer
Khoo Lip Hong (36391948) Developer

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
.\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
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

To deploy, push this repository to GitHub and choose **New > Blueprint** in
Render. Select the GitHub repository and apply the Blueprint. During setup,
provide `DATABASE_URL` using a connection string from Neon, Supabase, or
another PostgreSQL provider. The first API startup creates the PostgreSQL table
and imports `server/data/server_database.json` if the table is empty.

When Render asks for `CORS_ORIGINS`, enter the frontend URL once it is known,
for example `https://fit2101-frontend.onrender.com`. The browser client uses
the local API automatically on localhost and the Render API in production.

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

Update this section as your project grows.

```
src/
├── backend/
│   ├── auth.py
│   ├── constants.py
│   ├── create_project.py
│   ├── dashboard.py
│   ├── layout.py
│   ├── login.py
│   ├── project_layout.py
│   ├── server_data.py
│   ├── signup.py
│   ├── sprint-dashboard.py
│   ├── sprint-page.py
│   └── topbar.py
|
├── components/
│   ├── avatar.html
│   ├── project-sidebar.html
│   ├── sidebar.html
│   └── topbar.html
|
├── styles/
│   ├── auth.css
│   ├── base.css
│   ├── create-project.css
│   ├── dashboard.css
│   ├── layout.css
│   ├── project-layout.css
│   ├── snackbar.css
│   ├── sprint-dashboard.css
│   ├── sprint-page.css
│   └── topbar.css
|
├── views/
│   ├── create-project.html
│   ├── dashboard.html
│   ├── login.html
│   ├── project-page.html
│   ├── signup.html
│   ├── sprint-dashboard.html
│   └── sprint-page.html
│
├── index.html
├── PYSCRIPT_TUTORIAL.md
├── README.md
└── settings.json
```

## Notes

Keep your project work, documentation, setup instructions, and relevant artefacts in this repository.
Do not share this repository outside your group and the teaching team.
