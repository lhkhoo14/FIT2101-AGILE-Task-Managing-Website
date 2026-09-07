import sys
import asyncio

from models import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window # type: ignore
from auth import validate_email, validate_password, clear_errors, \
    show_feedback, show_snackbar, \
    toggle_password_mask

@when("submit", "#login-form")
async def handle_login(event):
    if event:
        event.preventDefault()
    
    clear_errors(["email", "password"])

    email = web.page["email"].value
    password = web.page["password"].value

    # 1. Validate Email
    is_email_valid, email_err = validate_email(email)
    if not is_email_valid:
        show_feedback("email", email_err)

    # 2. Validate Password
    is_pass_valid, pass_err = validate_password(password)
    if not is_pass_valid:
        show_feedback("password", pass_err)

    if not is_email_valid or not is_pass_valid:
        return

    db = ServerData()
    if db.find_user_by_email(email) is None:
        show_feedback("email", "No user found with this email.")
        return
    elif db.validate_login(email, password) is False:
        show_feedback("password", "Incorrect password. Please try again.")
        return

    await show_snackbar("Logging in...")

    window.location.href = "dashboard.html"

@when("click", "#toggle-password")
def handle_password_toggle(event):
    toggle_password_mask("password", "eye-icon", "eye-off-icon")