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
    default_structure = {"next_user_id": 1, "users": []}
    
    if not os.path.exists(DB_PATH):
        return {
            "next_user_id": 1,
            "next_project_id": 1,
            "users": [],
            "projects": {}
        }

    try:
        with open(DB_PATH, "r") as f:
            data = json.load(f)

            if not isinstance(data, dict):
                return {
                    "next_user_id": 1,
                    "next_project_id": 1,
                    "users": [],
                    "projects": {}
                }

            data.setdefault("next_user_id", 1)
            data.setdefault("next_project_id", 1)
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
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    project_id = db.get("next_project_id", 1)
    db["next_project_id"] = project_id + 1

    new_project = {
        "project_id": project_id,
        "name": payload.name,
        "description": payload.description,
        "members": [payload.user_id]
    }

    db["projects"][str(project_id)] = new_project

    # Add project to the user's projects
    user.setdefault("projects", [])
    user["projects"].append(project_id)

    write_db(db)

    return {
        "status": "success",
        "project": new_project
    }

@app.get("/api/projects")
def get_projects():
    db = read_db()

    return {
        "projects": list(db.get("projects", {}).values())
    }

@app.get("/api/users/{user_id}/projects")
def get_user_projects(user_id: int):
    db = read_db()
    
    # Check that user exists
    user = next((u for u in db["users"] if u["user_id"] == user_id), None)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Filter projects where user is a member
    all_projects = db.get("projects", {})
    user_projects = [
        project for project in all_projects.values()
        if user_id in project.get("members", [])
    ]

    return user_projects

@app.get("/api/projects/{project_id}")
def get_project(project_id: int, user_id: int):
    db = read_db()

    project = db.get("projects", {}).get(str(project_id))

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

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
