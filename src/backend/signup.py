import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window
from auth import validate_email, validate_signup_passwords, \
    clear_errors, show_feedback, show_snackbar, \
    toggle_password_mask

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

    is_pass_valid, pass_err = validate_signup_passwords(password, confirm_password)
    if not is_pass_valid:
        target_field = "confirm-password" if pass_err == "Passwords do not match." else "password"
        show_feedback(target_field, pass_err)

    if not is_email_valid or not is_pass_valid:
        return

    await show_snackbar("Account Created! Redirecting...")

    window.location.href = "login.html"

# 1. Main Password Field
@when("click", "#toggle-password")
def handle_password_toggle(event):
    toggle_password_mask("password", "eye-icon", "eye-off-icon")

# 2. Confirm Password Field
@when("click", "#toggle-confirm-password")
def handle_confirm_password_toggle(event):
    toggle_password_mask("confirm-password", "confirm-eye-icon", "confirm-eye-off-icon")