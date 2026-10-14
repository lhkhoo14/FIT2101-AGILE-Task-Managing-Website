import os
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

# --- SECTION: Account Settings (US-24) & Account Deletion (US-38) ---
import secrets
import hashlib
import hmac
import time
from pydantic import EmailStr
import mailer

class UpdateProfilePayload(BaseModel):
    username: str | None = None
    profile_photo: str | None = None

class EmailChangePayload(BaseModel):
    new_email: EmailStr

class EmailVerifyPayload(BaseModel):
    token: str

class PasswordChangePayload(BaseModel):
    current_password: str
    new_password: str

class DeleteAccountPayload(BaseModel):
    password: str

DEFAULT_PROFILE_PHOTO = "../assets/default-profile.svg"

@router.get("/users/{user_id}/settings")
def get_user_settings(user_id: int):
    user = db_manager.db["users"].get(str(user_id)) or db_manager.db["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user.get("id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "pending_email": user.get("pending_email"),
        "profile_photo": user.get("profile_photo", DEFAULT_PROFILE_PHOTO)
    }

@router.patch("/users/{user_id}/profile")
def update_user_profile(user_id: int, payload: UpdateProfilePayload):
    user = db_manager.db["users"].get(str(user_id)) or db_manager.db["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    updates = {}
    if payload.username is not None:
        uname = payload.username.strip()
        if not uname or len(uname) > 50:
            raise HTTPException(status_code=422, detail="Username must be between 1 and 50 characters.")
        for u in db_manager.db["users"].values():
            if str(u.get("id")) != str(user_id) and u.get("username", "").lower() == uname.lower():
                raise HTTPException(status_code=409, detail="That display name is already taken.")
        updates["username"] = uname

    if payload.profile_photo is not None:
        photo = payload.profile_photo
        if photo == "":
            updates["profile_photo"] = DEFAULT_PROFILE_PHOTO
        else:
            if not (photo.startswith("data:image/png;base64,") or photo.startswith("data:image/jpeg;base64,") or photo.startswith("data:image/webp;base64,")) or len(photo) > 300000:
                raise HTTPException(status_code=422, detail="Image is too large or not a supported type.")
            updates["profile_photo"] = photo

    def mutate(db):
        u = db["users"].get(str(user_id)) or db["users"].get(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        for k, v in updates.items():
            u[k] = v

    db_manager.update(mutate)
    return {"status": "success", "username": user.get("username"), "profile_photo": user.get("profile_photo", DEFAULT_PROFILE_PHOTO)}

@router.post("/users/{user_id}/email-change")
def request_email_change(user_id: int, payload: EmailChangePayload):
    user = db_manager.db["users"].get(str(user_id)) or db_manager.db["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    new_email = payload.new_email.strip()
    if new_email.lower() == user.get("email", "").lower():
        raise HTTPException(status_code=400, detail="New email cannot be the same as current email.")
    
    for u in db_manager.db["users"].values():
        if str(u.get("id")) != str(user_id) and u.get("email", "").lower() == new_email.lower():
            raise HTTPException(status_code=409, detail="Email is already registered.")

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = time.time() + 24 * 3600

    def mutate(db):
        u = db["users"].get(str(user_id)) or db["users"].get(user_id)
        if u:
            u["pending_email"] = new_email
            u["pending_email_token_hash"] = token_hash
            u["pending_email_expires"] = expires

    db_manager.update(mutate)
    
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5500")
    link = f"{frontend_url}/src/views/settings.html?verify_email={token}"
    email_sent = mailer.send_verification_email(new_email, link)
    return {"status": "success", "email_sent": email_sent}

@router.post("/users/email-verify")
def verify_email_change(payload: EmailVerifyPayload):
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    found_user = None
    for u in db_manager.db["users"].values():
        stored_hash = u.get("pending_email_token_hash")
        if stored_hash and hmac.compare_digest(stored_hash, token_hash):
            found_user = u
            break
            
    if not found_user:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    
    if time.time() > found_user.get("pending_email_expires", 0):
        def mutate_clear(db):
            for u in db["users"].values():
                if u.get("pending_email_token_hash") == token_hash:
                    u.pop("pending_email", None)
                    u.pop("pending_email_token_hash", None)
                    u.pop("pending_email_expires", None)
        db_manager.update(mutate_clear)
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")

    pending_email = found_user["pending_email"]
    for u in db_manager.db["users"].values():
        if str(u.get("id")) != str(found_user.get("id")) and u.get("email", "").lower() == pending_email.lower():
            raise HTTPException(status_code=409, detail="Email is already registered.")

    def mutate_verify(db):
        for u in db["users"].values():
            if u.get("pending_email_token_hash") == token_hash:
                u["email"] = u["pending_email"]
                u.pop("pending_email", None)
                u.pop("pending_email_token_hash", None)
                u.pop("pending_email_expires", None)

    db_manager.update(mutate_verify)
    return {"status": "success", "email": pending_email}

@router.post("/users/{user_id}/password")
def change_password(user_id: int, payload: PasswordChangePayload):
    user = db_manager.db["users"].get(str(user_id)) or db_manager.db["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not verify_password(payload.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters long.")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different from the current password.")

    new_hash = hash_password(payload.new_password)
    def mutate(db):
        u = db["users"].get(str(user_id)) or db["users"].get(user_id)
        if u:
            u["password_hash"] = new_hash

    db_manager.update(mutate)
    return {"status": "success"}

@router.post("/users/{user_id}/delete")
def delete_account(user_id: int, payload: DeleteAccountPayload):
    user = db_manager.db["users"].get(str(user_id)) or db_manager.db["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Password is incorrect.")

    def mutate(db):
        uid_str = str(user_id)
        projects_to_delete = []
        
        for pid, proj in list(db.get("projects", {}).items()):
            members = proj.get("members", [])
            is_member = any(str(m) == uid_str for m in members)
            if is_member:
                proj["members"] = [m for m in members if str(m) != uid_str]
                if "contribute" in proj and isinstance(proj["contribute"], list):
                    proj["contribute"] = [c for c in proj["contribute"] if str(c) != uid_str]
                if str(proj.get("creator")) == uid_str:
                    proj["creator"] = None
                
                roles = proj.get("roles", {})
                for rname, rlist in roles.items():
                    if isinstance(rlist, list):
                        roles[rname] = [r for r in rlist if str(r) != uid_str]
                
                if not proj["members"]:
                    projects_to_delete.append(pid)
                else:
                    roles.setdefault("Product Owner", [])
                    if not roles["Product Owner"]:
                        roles.setdefault("Scrum Master", [])
                        roles.setdefault("Member", [])
                        promoted = None
                        if roles["Scrum Master"]:
                            promoted = roles["Scrum Master"].pop(0)
                        elif roles["Member"]:
                            promoted = roles["Member"].pop(0)
                        else:
                            for m in proj["members"]:
                                promoted = m
                                break
                        if promoted is not None:
                            for rname, rlist in roles.items():
                                if rname != "Product Owner" and isinstance(rlist, list):
                                    roles[rname] = [x for x in rlist if str(x) != str(promoted)]
                            roles["Product Owner"].append(promoted)

            for s in proj.get("sprints", []):
                s_members = s.get("members", [])
                s["members"] = [m for m in s_members if str(m) != uid_str]
                kanban = s.get("kanban_state", {})
                for col_name, tasks in kanban.items():
                    if isinstance(tasks, list):
                        for t in tasks:
                            if str(t.get("assignee_id")) == uid_str:
                                t["assignee_id"] = None
                                t["assignee"] = None

        for pid in projects_to_delete:
            db["projects"].pop(pid, None)
            for u in db["users"].values():
                if "projects" in u and isinstance(u["projects"], list):
                    u["projects"] = [p for p in u["projects"] if str(p) != str(pid)]

        db["users"].pop(uid_str, None)

    db_manager.update(mutate)
    return {"status": "success"}