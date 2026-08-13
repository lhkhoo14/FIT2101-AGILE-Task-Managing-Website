import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web
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

    await show_snackbar("Login Successful! Redirecting...")
    await asyncio.sleep(2)

@when("click", "#toggle-password")
def handle_password_toggle(event):
    toggle_password_mask("password", "eye-icon", "eye-off-icon")