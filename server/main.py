from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import json, os

app = FastAPI()

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
        return {
            "next_user_id": 1,
            "next_project_id": 1,
            "users": [],
            "projects": {}
        }

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
    if not user or user["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
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

@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    db = read_db()

    project = db.get("projects", {}).get(str(project_id))

    if project is None:
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    return {
        "project": project
    }

@app.get("/api/users/{user_id}")
def get_user(user_id: int):
    db = read_db()
    user = next((u for u in db["users"] if u["user_id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user["user_id"], "username": user["username"], "email": user["email"]}

