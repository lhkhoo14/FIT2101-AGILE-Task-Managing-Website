from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
import time
import secrets
import string
from random import randint

from database_manager import db_manager
from security import hash_password, verify_password
from email_service import send_verification_email # type: ignore

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

def clean_expired_unverified_users(db):
    current_time = time.time()
    # 24 hours = 86400 seconds
    db["users"] = [
        u for u in db.get("users", []) 
        if u.get("is_verified", True) or (current_time - u.get("created_at", current_time) < 86400)
    ]

def generate_alphanumeric_code(length: int = 6) -> str:
    """Generates a secure 6-character alphanumeric code (Uppercase letters + Digits)."""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@router.post("/login")
def login(payload: LoginPayload):
    def mutate(db):
        clean_expired_unverified_users(db)
        
        user = next((u for u in db["users"] if u["email"] == payload.email), None)
        if not user:
            raise HTTPException(status_code=401, detail="Email is not registered.")

        if not user.get("is_verified", False):
            raise HTTPException(
                status_code=403, 
                detail="Account is unverified. Please input your 6-character code or check your email."
            )

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

class VerifyCodePayload(BaseModel):
    email: EmailStr
    code: str

@router.post("/verify-code")
def verify_with_code(payload: VerifyCodePayload):
    def mutate(db):
        clean_expired_unverified_users(db)
        user = next((u for u in db["users"] if u["email"] == payload.email), None)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        
        if user["is_verified"]:
            return {"status": "success", "message": "Account is already verified."}

        # Case-insensitive comparison for user convenience
        if user.get("verify_code") != payload.code.strip().upper():
            raise HTTPException(status_code=400, detail="Invalid verification code.")

        user["is_verified"] = True
        user.pop("verify_code", None)
        return {"status": "success", "message": "Email verified successfully!"}

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
        clean_expired_unverified_users(db)
        
        existing_user = next((u for u in db["users"] if u["email"] == payload.email), None)
        current_time = time.time()
        
        if existing_user:
            if existing_user["is_verified"]:
                raise HTTPException(status_code=400, detail="Email is already registered and verified.")
            else:
                # Check 1-minute cooldown (60 seconds)
                last_sent = existing_user.get("last_email_sent_at", 0)
                if current_time - last_sent < 60:
                    remaining_cooldown = int(60 - (current_time - last_sent))
                    raise HTTPException(
                        status_code=429, 
                        detail=f"Please wait {remaining_cooldown} seconds before requesting a new email."
                    )
                
                # Resend new 6-character alphanumeric code
                verify_code = generate_alphanumeric_code()
                
                existing_user["username"] = payload.username
                existing_user["password"] = hash_password(payload.password)
                existing_user["verify_code"] = verify_code
                existing_user["last_email_sent_at"] = current_time
                
                send_verification_email(payload.email, verify_code)
                return {"status": "success", "user_id": existing_user["user_id"], "message": "Verification email resent."}

        # Create new unverified user
        user_id = db.get("next_user_id", 1)
        db["next_user_id"] = user_id + 1
        
        verify_code = generate_alphanumeric_code()
        
        db["users"].append({
            "user_id": user_id,
            "username": payload.username,
            "email": payload.email,
            "password": hash_password(payload.password),
            "is_verified": False,
            "verify_code": verify_code,
            "created_at": current_time,
            "last_email_sent_at": current_time,
            "projects": []
        })
        
        send_verification_email(payload.email, verify_code)
        return {"status": "success", "user_id": user_id, "message": "Registration successful. Check your email for verification."}

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

class ResendCodePayload(BaseModel):
    email: EmailStr

@router.post("/resend-code")
def resend_verification_code(payload: ResendCodePayload):
    def mutate(db):
        clean_expired_unverified_users(db)
        user = next((u for u in db["users"] if u["email"] == payload.email), None)
        
        if not user:
            raise HTTPException(status_code=404, detail="Email is not registered.")
        if user["is_verified"]:
            raise HTTPException(status_code=400, detail="Account is already verified.")

        current_time = time.time()
        last_sent = user.get("last_email_sent_at", 0)
        
        # Check 1-minute cooldown (60 seconds)
        if current_time - last_sent < 60:
            remaining_cooldown = int(60 - (current_time - last_sent))
            raise HTTPException(
                status_code=429, 
                detail=f"Please wait {remaining_cooldown} seconds before requesting a new code."
            )

        # Generate new 6-character alphanumeric code
        verify_code = generate_alphanumeric_code()
        user["verify_code"] = verify_code
        user["last_email_sent_at"] = current_time
        
        send_verification_email(payload.email, verify_code)
        return {"status": "success", "message": "Verification code resent successfully."}

    return db_manager.update(mutate)