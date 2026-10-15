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
# These two have to match the presets defined in routes/projects.py, because the
# promotion below only helps if it lands in the role that actually carries the
# project's permissions in this app: "Project Creator" is the top role here, and
# the ordinary members' preset is "Employee" (there is no "Member" role).
ROLE_PRODUCT_OWNER = "Project Creator"
ROLE_SCRUM_MASTER = "Scrum Master"
ROLE_MEMBER = "Employee"
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


def _without(values, user_id):
    """Return a copy of a list with every entry equal to user_id (int or str) removed."""
    return [v for v in (values or []) if str(v) != str(user_id)]


def _ensure_roles(project):
    """Backfill roles on old projects (same rule as routes/projects.ensure_member_fields)."""
    members = project.get("members", [])
    if "roles" not in project:
        creators = project.get("creator", [])
        if not isinstance(creators, list):
            creators = [creators]
        owners = [m for m in members if any(str(m) == str(c) for c in creators)]
        project["roles"] = {
            ROLE_PRODUCT_OWNER: owners,
            ROLE_SCRUM_MASTER: [],
            ROLE_MEMBER: [m for m in members if m not in owners],
        }
    return project["roles"]


def _promote_if_no_owner(project):
    """If the project has no Product Owner left, promote the highest-ranking member.

    Ranking: Scrum Master, then Member, then anyone remaining in `members`.
    """
    roles = project["roles"]
    roles.setdefault(ROLE_PRODUCT_OWNER, [])
    roles.setdefault(ROLE_SCRUM_MASTER, [])
    roles.setdefault(ROLE_MEMBER, [])
    if roles[ROLE_PRODUCT_OWNER]:
        return

    if roles[ROLE_SCRUM_MASTER]:
        promoted = roles[ROLE_SCRUM_MASTER][0]
    elif roles[ROLE_MEMBER]:
        promoted = roles[ROLE_MEMBER][0]
    else:
        promoted = project["members"][0]

    for name, holders in roles.items():
        if isinstance(holders, list):
            roles[name] = _without(holders, promoted)
    roles[ROLE_PRODUCT_OWNER].append(promoted)


def _unassign_tasks(sprint, user):
    state = sprint.get("kanban_state") or {}
    names = {
        str(user.get("username", "")).lower(),
        str(user.get("email", "")).lower(),
    } - {""}
    for column in KANBAN_COLUMNS:
        for task in state.get(column, []) or []:
            assignee_id = task.get("assignee_id")
            if assignee_id is not None:
                matches = str(assignee_id) == str(user["user_id"])
            else:
                matches = str(task.get("assignee") or "").lower() in names
            if matches:
                task["assignee_id"] = None
                task["assignee"] = None


@router.post("/users/{user_id}/delete")
def delete_account(user_id: int, payload: DeleteAccountPayload):
    def mutate(db):
        user = _find_user(db, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if not verify_password(payload.password, user["password"]):
            raise HTTPException(status_code=401, detail="Password is incorrect.")

        deleted_projects = []
        for pid, project in list(db.get("projects", {}).items()):
            if not any(str(m) == str(user_id) for m in project.get("members", [])):
                continue

            _ensure_roles(project)   # must run BEFORE the user is removed
            project["members"] = _without(project.get("members"), user_id)
            if "contribute" in project:
                project["contribute"] = _without(project["contribute"], user_id)
            creators = project.get("creator", [])
            project["creator"] = (
                _without(creators, user_id) if isinstance(creators, list)
                else (None if str(creators) == str(user_id) else creators)
            )
            for name, holders in project["roles"].items():
                if isinstance(holders, list):
                    project["roles"][name] = _without(holders, user_id)
            if isinstance(project.get("contributions"), dict):
                project["contributions"].pop(str(user_id), None)

            if not project["members"]:
                # The user was the sole remaining member: clean the project up.
                deleted_projects.append(pid)
                continue

            _promote_if_no_owner(project)
            for sprint in project.get("sprints", []):
                if sprint.get("members") is not None:
                    sprint["members"] = _without(sprint["members"], user_id)
                _unassign_tasks(sprint, user)

        for pid in deleted_projects:
            db["projects"].pop(pid, None)
        removed = {str(d) for d in deleted_projects}
        for other in db["users"]:
            if "projects" in other:
                other["projects"] = [p for p in other["projects"] if str(p) not in removed]

        # Remove the user. next_user_id is deliberately left alone so ids are never reused.
        db["users"] = [u for u in db["users"] if str(u.get("user_id")) != str(user_id)]
        return {"status": "success"}

    return db_manager.update(mutate)