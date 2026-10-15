import os
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr
import time
from database_manager import db_manager
from security import hash_password, verify_password
import logic.membership_logic as membership_logic
from routes.activity import refresh_contributions

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

ALLOWED_PHOTO_PREFIXES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/webp;base64,",
)
MAX_PHOTO_LENGTH = 300000
ROLE_PRODUCT_OWNER = "Product Owner"
ROLE_SCRUM_MASTER = "Scrum Master"
ROLE_MEMBER = "Member"
KANBAN_COLUMNS = ("backlog", "active", "review", "completed")


def _find_user(db, user_id):
    """Users are stored as a list of dicts keyed by `user_id`."""
    return next(
        (u for u in db.get("users", []) if str(u.get("user_id")) == str(user_id)),
        None
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clear_pending_email(user):
    user.pop("pending_email", None)
    user.pop("pending_email_token_hash", None)
    user.pop("pending_email_expires", None)


@router.get("/users/{user_id}/settings")
def get_user_settings(user_id: int):
    db = db_manager.read()
    user = _find_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user["email"],
        "pending_email": user.get("pending_email"),
        "profile_photo": user.get("profile_photo", DEFAULT_PROFILE_PHOTO)
    }


@router.patch("/users/{user_id}/profile")
def update_user_profile(user_id: int, payload: UpdateProfilePayload):
    def mutate(db):
        user = _find_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if payload.username is not None:
            name = payload.username.strip()
            if not name or len(name) > 50:
                raise HTTPException(
                    status_code=422,
                    detail="Display name must be between 1 and 50 characters."
                )
            # Members are looked up by username, so it has to stay unique.
            if any(
                str(u.get("user_id")) != str(user_id)
                and str(u.get("username", "")).lower() == name.lower()
                for u in db["users"]
            ):
                raise HTTPException(status_code=409, detail="That display name is already taken.")
            user["username"] = name

        if payload.profile_photo is not None:
            photo = payload.profile_photo
            if photo == "":
                user.pop("profile_photo", None)
            elif not photo.startswith(ALLOWED_PHOTO_PREFIXES) or len(photo) > MAX_PHOTO_LENGTH:
                raise HTTPException(
                    status_code=422,
                    detail="Image is too large or not a supported type."
                )
            else:
                user["profile_photo"] = photo

        return {
            "status": "success",
            "username": user["username"],
            "profile_photo": user.get("profile_photo", DEFAULT_PROFILE_PHOTO)
        }

    return db_manager.update(mutate)


@router.post("/users/{user_id}/email-change")
def request_email_change(user_id: int, payload: EmailChangePayload):
    new_email = payload.new_email.strip()
    token = secrets.token_urlsafe(32)

    def mutate(db):
        user = _find_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if new_email.lower() == str(user.get("email", "")).lower():
            raise HTTPException(status_code=400, detail="That is already your current email address.")
        if any(
            str(u.get("user_id")) != str(user_id)
            and str(u.get("email", "")).lower() == new_email.lower()
            for u in db["users"]
        ):
            raise HTTPException(status_code=409, detail="Email is already registered.")

        # The current email is NOT changed until the link is confirmed.
        # A new request overwrites any earlier pending one.
        user["pending_email"] = new_email
        user["pending_email_token_hash"] = _hash_token(token)
        user["pending_email_expires"] = time.time() + 24 * 3600

    db_manager.update(mutate)

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5500").rstrip("/")
    link = f"{frontend_url}/src/views/settings.html?verify_email={token}"
    email_sent = mailer.send_verification_email(new_email, link)
    return {"status": "success", "email_sent": email_sent}


@router.post("/users/email-verify")
def verify_email_change(payload: EmailVerifyPayload):
    token_hash = _hash_token(payload.token)
    invalid = HTTPException(
        status_code=400,
        detail="This verification link is invalid or has expired."
    )
    result = {}

    def mutate(db):
        user = next(
            (
                u for u in db.get("users", [])
                if u.get("pending_email_token_hash")
                and hmac.compare_digest(u["pending_email_token_hash"], token_hash)
            ),
            None
        )
        if user is None:
            return "invalid"

        if time.time() > user.get("pending_email_expires", 0):
            _clear_pending_email(user)
            return "invalid"

        pending = user.get("pending_email")
        if not pending:
            return "invalid"
        if any(
            u is not user and str(u.get("email", "")).lower() == pending.lower()
            for u in db["users"]
        ):
            return "taken"

        user["email"] = pending
        _clear_pending_email(user)
        result["email"] = pending
        return "ok"

    outcome = db_manager.update(mutate)
    if outcome == "taken":
        raise HTTPException(status_code=409, detail="Email is already registered.")
    if outcome != "ok":
        raise invalid
    return {"status": "success", "email": result["email"]}


@router.post("/users/{user_id}/password")
def change_password(user_id: int, payload: PasswordChangePayload):
    def mutate(db):
        user = _find_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not verify_password(payload.current_password, user["password"]):
            raise HTTPException(status_code=401, detail="Current password is incorrect.")
        if len(payload.new_password) < 8:
            raise HTTPException(
                status_code=422,
                detail="New password must be at least 8 characters long."
            )
        if payload.current_password == payload.new_password:
            raise HTTPException(
                status_code=400,
                detail="New password must be different from the current password."
            )
        user["password"] = hash_password(payload.new_password)
        return {"status": "success"}

    return db_manager.update(mutate)


@router.post("/users/{user_id}/delete", status_code=status.HTTP_200_OK)
def delete_account(user_id: int, payload: DeleteAccountPayload):
    """Delete the caller's own account and unlink them from every project.

    Self-service, and confirmed with the account's own password: there is no
    route that lets one user delete another user's account, however privileged
    their role, because a password can only be supplied by the person holding it.
    The cascade removes the user record and every reference to it - project
    membership, role assignments, sprint membership and task assignments - while
    keeping the projects, the tasks and the logged work, so nothing a team built
    disappears because one person left.

    Refused while the user is the sole Project Creator of a project they are
    still a member of: removing them would leave that project with no owner and
    nobody able to appoint one. That role has to be handed over first.
    """
    # The password is checked before the transaction opens, so bcrypt is not
    # holding the application_state row lock while it runs.
    db = db_manager.read()
    user = next((u for u in db.get("users", []) if str(u.get("user_id")) == str(user_id)), None)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.get("password") or not verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=401, detail="Incorrect password.")

    def mutate(db):
        user = next((u for u in db.get("users", []) if str(u.get("user_id")) == str(user_id)), None)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        projects = list(db.get("projects", {}).values())
        blocking = membership_logic.sole_creator_projects(projects, user_id)
        if blocking:
            names = ", ".join(sorted(project.get("name", "Untitled project") for project in blocking))
            noun = "project" if len(blocking) == 1 else "projects"
            raise HTTPException(
                status_code=409,
                detail=(
                    f"You are the only Project Creator of the following {noun}: {names}. "
                    "Give that role to another member before deleting your account."
                ),
            )

        for project in projects:
            membership_logic.detach_member(project, user_id)
            refresh_contributions(db, project)

        username = user.get("username") or f"User {user_id}"
        db["users"] = [u for u in db.get("users", []) if str(u.get("user_id")) != str(user_id)]

        return {"status": "success", "message": f"Account '{username}' deleted."}

    return db_manager.update(mutate)
