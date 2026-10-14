import sys
import asyncio
import re
from auth import show_snackbar
from server_data import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window  # type: ignore
from auth import show_feedback, clear_errors, toggle_password_mask

# Global lockout task reference to prevent overlapping timers
lockout_task = None

async def start_lockout_timer(seconds: int):
    """Disables the login button and displays a live countdown timer in the password error message."""
    login_btn = web.page["#login-btn"]

    if login_btn:
        login_btn.disabled = True
        login_btn.classes.add("disabled")

    for remaining in range(seconds, 0, -1):
        show_feedback("password", "password-error", f"Too many failed attempts. Try again in {remaining}s.")
        if login_btn:
            login_btn.innerText = f"Locked ({remaining}s)"
        await asyncio.sleep(1)

    # Reset UI when lockout expires
    if login_btn:
        login_btn.disabled = False
        login_btn.classes.remove("disabled")
        login_btn.innerText = "Log In"
    
    clear_errors(["email", "password"])


@when("submit", "#login-form")
async def handle_login(event):
    if event:
        event.preventDefault()

    global lockout_task

    if lockout_task and not lockout_task.done():
        return

    clear_errors(["email", "password"])

    email = web.page["#email"].value.strip()
    password = web.page["#password"].value.strip()

    db = ServerData()
    success, message = await db.validate_login(email, password)

    if success:
        window.location.replace("dashboard.html")
    else:
        # Ensure message is converted to string
        msg_str = str(message) if not isinstance(message, str) else message
        msg_lower = msg_str.lower()

        # 1. Unregistered Email
        if "not registered" in msg_lower or "email" in msg_lower:
            show_feedback("email", "email-error", msg_str)

        # 2. Lockout Triggered or Currently Locked Out
        elif "locked" in msg_lower or "try again" in msg_lower:
            match = re.search(r"(\d+)\s*seconds?", msg_str, re.IGNORECASE)
            if match:
                duration = int(match.group(1))
                if lockout_task and not lockout_task.done():
                    lockout_task.cancel()
                lockout_task = asyncio.ensure_future(start_lockout_timer(duration))
            else:
                show_feedback("password", "password-error", msg_str)

        # 3. Incorrect Password (Attempts Remaining)
        else:
            show_feedback("password", "password-error", msg_str)


@when("click", "#toggle-password")
def handle_password_toggle(event):
    toggle_password_mask("password", "eye-icon", "eye-off-icon")

    # --- SECTION: Account deleted message (US-38) ---
try:
    msg = window.sessionStorage.getItem("account_deleted_message")
    if msg:
        window.sessionStorage.removeItem("account_deleted_message")
        asyncio.ensure_future(show_snackbar(msg, 4))
except Exception:
    pass