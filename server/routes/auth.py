import os
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
import time
import secrets
import string
from random import randint

from database_manager import db_manager
from security import hash_password, verify_password
import mailer

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
        
        # Block verified accounts from going through verification again
        if user.get("is_verified", False):
            raise HTTPException(status_code=400, detail="Account is already verified.")

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
                
                mailer.send_verification_code(payload.email, verify_code)
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
        
        mailer.send_verification_code(payload.email, verify_code)
        return {"status": "success", "user_id": user_id, "message": "Registration successful. Check your email for verification."}

    return db_manager.update(mutate)

@router.get("/users/{user_id}")
def get_user(user_id: int, request: Request):
    user = db_manager.find_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user["email"],
        "profile_photo": _photo_url(request, user),
    }

@router.get("/users")
def get_users(user_id: int, request: Request):
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
            "profile_photo": _photo_url(request, user),
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
            
        # Prevent sending codes to already verified accounts
        if user.get("is_verified", False):
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
        
        mailer.send_verification_code(payload.email, verify_code)
        return {"status": "success", "message": "Verification code resent successfully."}

    return db_manager.update(mutate)

# --- SECTION: Account Settings (US-24) & Account Deletion (US-38) ---
import base64
import secrets
import hashlib
import hmac

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

# What each accepted data URL prefix means, and the magic bytes its payload has
# to start with. The prefix alone would let any bytes through behind an image
# label, so both are checked before anything is stored.
PHOTO_TYPES = {
    "data:image/png;base64,": ("image/png", b"\x89PNG\r\n\x1a\n"),
    "data:image/jpeg;base64,": ("image/jpeg", b"\xff\xd8\xff"),
    "data:image/webp;base64,": ("image/webp", b"RIFF"),
}


def _decode_photo(photo: str) -> tuple[str, bytes]:
    """Validate one of the browser data URLs and return (content type, bytes)."""
    for prefix, (content_type, magic) in PHOTO_TYPES.items():
        if not photo.startswith(prefix):
            continue
        try:
            data = base64.b64decode(photo[len(prefix):], validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="That image could not be read.")
        if not data.startswith(magic):
            raise HTTPException(status_code=422, detail="That image could not be read.")
        return content_type, data
    raise HTTPException(status_code=422, detail="Image is too large or not a supported type.")


def _photo_url(request: Request, user) -> str:
    """Where the browser should fetch this user picture from.

    The frontend is served from a different origin than this API, so the URL has
    to be absolute. url_for() builds it from the route and the host the caller
    used, which keeps it right locally, on Render and in the tests without
    another setting to keep in sync.
    """
    if user.get("has_avatar"):
        version = user.get("avatar_updated_at") or 0
        return f"{request.url_for('get_user_avatar', user_id=user['user_id'])}?v={version}"
    stored = str(user.get("profile_photo") or "")
    # A picture saved before avatars moved into their own table.
    return stored if stored.startswith("data:") else DEFAULT_PROFILE_PHOTO


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
def get_user_settings(user_id: int, request: Request):
    db = db_manager.read()
    user = _find_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "email": user["email"],
        "pending_email": user.get("pending_email"),
        "profile_photo": _photo_url(request, user),
    }


@router.get("/users/{user_id}/avatar")
def get_user_avatar(user_id: int, request: Request):
    """Serve one user profile picture.

    The bytes live in their own table, so this is the only request that pays for
    them, and they can be reused from the browser cache: the ETag changes only
    when the picture does.
    """
    avatar = db_manager.get_user_avatar(user_id)
    if avatar is None:
        raise HTTPException(status_code=404, detail="This user has no profile picture.")

    content_type, data = avatar
    etag = "\"" + hashlib.sha256(data).hexdigest()[:32] + "\""
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    return Response(
        content=data,
        media_type=content_type,
        headers={"ETag": etag, "Cache-Control": "private, max-age=300"},
    )


@router.patch("/users/{user_id}/profile")
def update_user_profile(user_id: int, payload: UpdateProfilePayload, request: Request):
    # The picture is validated, and its bytes written, before the shared state
    # document is touched: the image lives in its own table, and a rejected one
    # must not leave the account pointing at something that is not there.
    avatar = None
    remove_avatar = False
    if payload.profile_photo is not None:
        if payload.profile_photo == "":
            remove_avatar = True
        elif len(payload.profile_photo) > MAX_PHOTO_LENGTH:
            raise HTTPException(
                status_code=422,
                detail="Image is too large or not a supported type."
            )
        else:
            avatar = _decode_photo(payload.profile_photo)

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

        if avatar is not None:
            # The bytes are in user_avatars; this record only remembers that there
            # is a picture and when it changed, which is what the URL carries.
            user["has_avatar"] = True
            user["avatar_updated_at"] = int(time.time())
            user.pop("profile_photo", None)
        elif remove_avatar:
            user.pop("has_avatar", None)
            user.pop("avatar_updated_at", None)
            user.pop("profile_photo", None)

        return {
            "status": "success",
            "username": user["username"],
            "profile_photo": _photo_url(request, user)
        }

    if avatar is not None:
        db_manager.save_user_avatar(user_id, avatar[0], avatar[1])
    elif remove_avatar:
        db_manager.delete_user_avatar(user_id)

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

class ForgotPasswordPayload(BaseModel):
    email: EmailStr

class ResetPasswordPayload(BaseModel):
    email: EmailStr
    code: str
    new_password: str

@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordPayload):
    def mutate(db):
        clean_expired_unverified_users(db)
        user = next((u for u in db["users"] if u["email"] == payload.email), None)
        
        # Check if email is registered and verified
        if not user:
            raise HTTPException(status_code=404, detail="Email is not registered.")
        if not user.get("is_verified", False):
            raise HTTPException(status_code=400, detail="Account is not verified.")

        current_time = time.time()
        last_sent = user.get("last_reset_sent_at", 0)
        
        # Enforce 1-minute (60 seconds) cooldown
        if current_time - last_sent < 60:
            remaining_cooldown = int(60 - (current_time - last_sent))
            raise HTTPException(
                status_code=429, 
                detail=f"Please wait {remaining_cooldown} seconds before requesting a new code."
            )

        reset_code = generate_alphanumeric_code()
        user["reset_code"] = reset_code
        user["reset_code_expires_at"] = current_time + 900  # Expires in 15 minutes
        user["last_reset_sent_at"] = current_time
        
        mailer.send_password_reset_code(payload.email, reset_code)
        return {"status": "success", "message": "Password reset code sent successfully."}

    return db_manager.update(mutate)

@router.post("/reset-password")
def reset_password(payload: ResetPasswordPayload):
    def mutate(db):
        clean_expired_unverified_users(db)
        user = next((u for u in db["users"] if u["email"] == payload.email), None)
        
        if not user:
            raise HTTPException(status_code=404, detail="Email is not registered.")
        if not user.get("is_verified", False):
            raise HTTPException(status_code=400, detail="Account is not verified.")

        if user.get("reset_code") != payload.code.strip().upper():
            raise HTTPException(status_code=400, detail="Invalid reset code.")

        if time.time() > user.get("reset_code_expires_at", 0):
            raise HTTPException(status_code=400, detail="Reset code has expired. Please request a new one.")

        if len(payload.new_password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters long.")

        user["password"] = hash_password(payload.new_password)
        user.pop("reset_code", None)
        user.pop("reset_code_expires_at", None)
        
        return {"status": "success", "message": "Password reset successfully. You can now log in."}

    return db_manager.update(mutate)