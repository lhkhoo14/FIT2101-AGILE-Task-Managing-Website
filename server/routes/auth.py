from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
import time
from database_manager import db_manager
from security import hash_password, verify_password

router = APIRouter()

# Fallback avatar (path is relative to src/views/, where the pages that display it live).
DEFAULT_PROFILE_PHOTO = "../assets/default-profile.svg"

class LoginPayload(BaseModel):
    email: EmailStr
    password: str

class RegisterPayload(BaseModel):
    email: EmailStr
    username: str
    password: str

@router.post("/login")
def login(payload: LoginPayload):
    def mutate(db):
        user = next((u for u in db["users"] if u["email"] == payload.email), None)
        if not user:
            raise HTTPException(status_code=401, detail="Email is not registered.")

        current_time = time.time()
        lockout_until = user.get("lockout_until", 0)
        if current_time < lockout_until:
            remaining_seconds = int(lockout_until - current_time)
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {remaining_seconds} seconds."
            )

        if not verify_password(payload.password, user["password"]):
            failed_attempts = user.get("failed_attempts", 0) + 1
            user["failed_attempts"] = failed_attempts
            lockout_time = 0
            if failed_attempts % 3 == 0:
                lockout_time = (failed_attempts // 3) * 30
                user["lockout_until"] = current_time + lockout_time
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

        user["failed_attempts"] = 0
        user["lockout_until"] = 0
        return {"status": "success", "user_id": user["user_id"]}

    return db_manager.update(mutate)

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload):
    def mutate(db):
        if any(u["email"] == payload.email for u in db["users"]):
            raise HTTPException(status_code=400, detail="Email is already registered.")
        user_id = db.get("next_user_id", 1)
        db["next_user_id"] = user_id + 1
        db["users"].append({
            "user_id": user_id,
            "username": payload.username,
            "email": payload.email,
            "password": hash_password(payload.password),
            "projects": []
        })
        return {"status": "success", "user_id": user_id}

    return db_manager.update(mutate)

@router.get("/users/{user_id}")
def get_user(user_id: int):
    user = db_manager.find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user["email"],
        "profile_photo": user.get("profile_photo", DEFAULT_PROFILE_PHOTO)
    }

@router.get("/users")
def get_users(user_id: int):
    # CHANGE: single read. find_user_by_id() reads the database again to validate
    # a session we can check against the snapshot we are about to return anyway.
    db = db_manager.read()
    if not any(u["user_id"] == user_id for u in db.get("users", [])):
        raise HTTPException(status_code=401, detail="Session is invalid.")
    return [
        {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "profile_photo": user.get("profile_photo", DEFAULT_PROFILE_PHOTO)
        }
        for user in db["users"]
    ]