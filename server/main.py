from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import json, os
import time

app = FastAPI() # To run the server, place `uvicorn main:app --reload` in the terminal.

# Enable CORS so PyScript running in the browser can communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(
    os.path.dirname(__file__),
    "data",
    "server_database.json"
)

def read_db() -> dict:
    default_structure = {
        "next_user_id": 1, 
        "next_project_id": 1, 
        "next_backlog_id": 1, 
        "next_sprint_id": 1, 
        "users": [], 
        "projects": {}
    }
    if not os.path.exists(DB_PATH):
        return default_structure

    try:
        with open(DB_PATH, "r") as f:
            data = json.load(f)

            if not isinstance(data, dict):
                return default_structure
            data.setdefault("next_user_id", 1)
            data.setdefault("next_project_id", 1)
            data.setdefault("next_backlog_id", 1)
            data.setdefault("next_sprint_id", 1)
            data.setdefault("users", [])
            data.setdefault("projects", {})
            
            return data
    except (json.JSONDecodeError, Exception):
        return default_structure

def write_db(data: dict):
    dir_name = os.path.dirname(DB_PATH)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(DB_PATH, "w") as f:
        json.dump(data, f, indent=4)

class LoginPayload(BaseModel):
    email: EmailStr
    password: str

class RegisterPayload(BaseModel):
    email: EmailStr
    username: str
    password: str

class CreateProjectPayload(BaseModel):
    user_id: int
    name: str
    description: str

class CreateBacklogPayload(BaseModel):
    user_id: int
    title: str
    tag: str
    priority: str

class CreateSprintPayload(BaseModel):
    user_id: int
    name: str
    details: str
    status: str

class MoveBacklogPayload(BaseModel):
    user_id: int
    backlog_id: int

@app.post("/api/login")
def login(payload: LoginPayload):
    db = read_db()
    user = next((u for u in db["users"] if u["email"] == payload.email), None)

    # 1. Unregistered email error
    if not user:
        raise HTTPException(status_code=401, detail="Email is not registered.")

    current_time = time.time()
    lockout_until = user.get("lockout_until", 0)

    # 2. Account locked out error
    if current_time < lockout_until:
        remaining_seconds = int(lockout_until - current_time)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {remaining_seconds} seconds."
        )

    # 3. Password mismatch error
    if user["password"] != payload.password:
        failed_attempts = user.get("failed_attempts", 0) + 1
        user["failed_attempts"] = failed_attempts

        lockout_time = 0
        if failed_attempts % 3 == 0:
            multiplier = failed_attempts // 3
            lockout_time = multiplier * 30  # 30s -> 60s -> 90s
            user["lockout_until"] = current_time + lockout_time

        write_db(db)

        if lockout_time > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Account locked for {lockout_time} seconds."
            )
        
        attempts_left = 3 - (failed_attempts % 3)
        raise HTTPException(
            status_code=401,
            detail=f"Incorrect password. {attempts_left} attempt(s) remaining before lockout."
        )

    # Successful login: reset counters
    user["failed_attempts"] = 0
    user["lockout_until"] = 0
    write_db(db)

    return {"status": "success", "user_id": user["user_id"]}

@app.post("/api/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload):
    db = read_db()
    if any(u["email"] == payload.email for u in db["users"]):
        raise HTTPException(status_code=400, detail="Email is already registered.")

    user_id = db.get("next_user_id", 1)
    db["next_user_id"] = user_id + 1

    new_user = {
        "user_id": user_id,
        "username": payload.username,
        "email": payload.email,
        "password": payload.password,
        "projects": []
    }
    db["users"].append(new_user)
    write_db(db)

    return {"status": "success", "user_id": user_id}

@app.post("/api/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectPayload):
    db = read_db()

    # Check that the user exists
    user = next(
        (u for u in db["users"] if u["user_id"] == payload.user_id),
        None
    )

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    project_id = db.get("next_project_id", 1)
    db["next_project_id"] = project_id + 1

    new_project = {
        "project_id": project_id,
        "name": payload.name,
        "description": payload.description,
        "creator": [payload.user_id],
        "members": [payload.user_id],
        "backlog": [],
        "sprints": []
    }

    db["projects"][str(project_id)] = new_project

    # Add project to the user's projects
    user.setdefault("projects", [])
    user["projects"].append(project_id)

    write_db(db)
    return {"status": "success", "project": new_project}

@app.get("/api/users/{user_id}/projects")
def get_user_projects(user_id: int):
    db = read_db()
    
    # Check that user exists
    user = next((u for u in db["users"] if u["user_id"] == user_id), None)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Filter projects where user is a member
    all_projects = db.get("projects", {})
    return [p for p in all_projects.values() if user_id in p.get("members", [])]

@app.get("/api/projects/{project_id}")
def get_project(project_id: int, user_id: int):
    db = read_db()

    project = db.get("projects", {}).get(str(project_id))

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Security Check: Verify user membership
    members = project.get("members", [])
    if user_id not in members:
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: You are not a member of this project"
        )
    return project

@app.get("/api/users/{user_id}")
def get_user(user_id: int):
    db = read_db()
    user = next((u for u in db["users"] if u["user_id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user["user_id"], "username": user["username"], "email": user["email"]}

# --- Backlog & Sprint Endpoints ---

@app.get("/api/projects/{project_id}/backlog")
def get_project_backlog(project_id: int, user_id: int):
    project = get_project(project_id, user_id)
    return project.get("backlog", [])

@app.post("/api/projects/{project_id}/backlog", status_code=status.HTTP_201_CREATED)
def create_backlog_item(project_id: int, payload: CreateBacklogPayload):
    db = read_db()
    project = db.get("projects", {}).get(str(project_id))
    if not project or payload.user_id not in project.get("members", []):
        raise HTTPException(status_code=403, detail="Access denied")

    backlog_id = db.get("next_backlog_id", 1)
    db["next_backlog_id"] = backlog_id + 1

    item = {
        "id": backlog_id,
        "title": payload.title,
        "tag": payload.tag,
        "priority": payload.priority
    }
    project.setdefault("backlog", []).append(item)
    write_db(db)
    return item

@app.get("/api/projects/{project_id}/sprints")
def get_project_sprints(project_id: int, user_id: int):
    project = get_project(project_id, user_id)
    return project.get("sprints", [])

@app.post("/api/projects/{project_id}/sprints", status_code=status.HTTP_201_CREATED)
def create_sprint(project_id: int, payload: CreateSprintPayload):
    db = read_db()
    project = db.get("projects", {}).get(str(project_id))
    if not project or payload.user_id not in project.get("members", []):
        raise HTTPException(status_code=403, detail="Access denied")

    sprint_id = db.get("next_sprint_id", 1)
    db["next_sprint_id"] = sprint_id + 1

    sprint = {
        "id": str(sprint_id),
        "name": payload.name,
        "details": payload.details,
        "status": payload.status,
        "backlog": []
    }
    project.setdefault("sprints", []).append(sprint)
    write_db(db)
    return sprint

@app.get("/api/projects/{project_id}/sprints/{sprint_id}/backlog")
def get_sprint_backlog(project_id: int, sprint_id: str, user_id: int):
    project = get_project(project_id, user_id)
    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint.get("backlog", [])

@app.post("/api/projects/{project_id}/sprints/{sprint_id}/backlog")
def move_backlog_to_sprint(project_id: int, sprint_id: str, payload: MoveBacklogPayload):
    db = read_db()
    project = db.get("projects", {}).get(str(project_id))
    if not project or payload.user_id not in project.get("members", []):
        raise HTTPException(status_code=403, detail="Access denied")

    backlog = project.get("backlog", [])
    item_idx = next((i for i, item in enumerate(backlog) if str(item["id"]) == str(payload.backlog_id)), None)
    if item_idx is None:
        raise HTTPException(status_code=404, detail="Backlog item not found in project backlog")

    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")

    item = backlog.pop(item_idx)
    sprint.setdefault("backlog", []).append(item)
    write_db(db)
    return {"status": "success"}