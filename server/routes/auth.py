from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
import time
import secrets

from database_manager import db_manager
from security import hash_password, verify_password
from email import send_verification_email # type: ignore

router = APIRouter()

# Fallback avatar (path is relative to src/views/, where the pages that display it live).
DEFAULT_PROFILE_PHOTO = "../assets/default-profile.svg"

class LoginPayload(BaseModel):
    email: EmailStr
    password: str

class CheckEmailPayload(BaseModel):
    email: EmailStr

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

@router.post("/register/check-email")
def check_email(payload: CheckEmailPayload):
    db = db_manager.read()
    if any(u["email"] == payload.email for u in db["users"]):
        raise HTTPException(status_code=400, detail="Email is already registered.")
    return {"status": "success", "message": "Email is available. Proceed to details."}

@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload):
    def mutate(db):
        # Check if email already exists
        existing_user = next((u for u in db["users"] if u["email"] == payload.email), None)
        
        if existing_user:
            if existing_user["is_verified"]:
                raise HTTPException(status_code=400, detail="Email is already registered and verified.")
            else:
                # If the account exists but is UNVERIFIED, update details and resend token!
                verify_token = secrets.token_urlsafe(32)
                existing_user["username"] = payload.username
                existing_user["password"] = hash_password(payload.password)
                existing_user["verify_token"] = verify_token
                
                send_verification_email(payload.email, verify_token)
                return {"status": "success", "user_id": existing_user["user_id"], "message": "Verification email resent."}

        # Otherwise, create a new unverified user
        user_id = db.get("next_user_id", 1)
        db["next_user_id"] = user_id + 1
        
        verify_token = secrets.token_urlsafe(32)
        db["users"].append({
            "user_id": user_id,
            "username": payload.username,
            "email": payload.email,
            "password": hash_password(payload.password),
            "is_verified": False,
            "verify_token": verify_token,
            "projects": []
        })
        
        send_verification_email(payload.email, verify_token)
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