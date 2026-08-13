import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web
from auth import validate_email, validate_signup_passwords, clear_errors, show_feedback, show_snackbar

@when("submit", "#signup-form")
async def handle_signup(event):
    if event:
        event.preventDefault()

    clear_errors(["email", "password", "confirm-password"])

    email = web.page["email"].value
    password = web.page["password"].value
    confirm_password = web.page["confirm-password"].value

    is_email_valid, email_err = validate_email(email)
    if not is_email_valid:
        show_feedback("email", email_err)
        return

    is_pass_valid, pass_err = validate_signup_passwords(password, confirm_password)
    if not is_pass_valid:
        target_field = "confirm-password" if pass_err == "Passwords do not match." else "password"
        show_feedback(target_field, pass_err)
        return

    show_snackbar("Account Created! Redirecting...")
    await asyncio.sleep(2)