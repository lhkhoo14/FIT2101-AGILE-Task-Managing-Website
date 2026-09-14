from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
import json, os

app = FastAPI() # To run the server, place `uvicorn main:app --reload` in the terminal.

# Enable CORS so PyScript running in the browser can communicate with FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "./data/server_database.json"

def read_db() -> dict:
    default_structure = {"next_user_id": 1, "users": []}
    
    if not os.path.exists(DB_PATH):
        return default_structure
    try:
        with open(DB_PATH, "r") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return default_structure
            
            # Guarantee required keys exist
            if "users" not in data or not isinstance(data["users"], list):
                data["users"] = []
            if "next_user_id" not in data or not isinstance(data["next_user_id"], int):
                data["next_user_id"] = 1
                
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
        "password": payload.password
    }
    db["users"].append(new_user)
    write_db(db)

    return {"status": "success", "user_id": user_id}

@app.get("/api/users/{user_id}")
def get_user(user_id: int):
    db = read_db()
    user = next((u for u in db["users"] if u["user_id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"user_id": user["user_id"], "username": user["username"], "email": user["email"]}