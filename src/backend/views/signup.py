import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window  # type: ignore
from server_data import ServerData
from auth import ( # type: ignore
    validate_email,
    validate_password,
    clear_errors,
    show_feedback,
    show_snackbar,
    toggle_password_mask,
)

@when("click", "#submit-btn")
async def handle_signup(event):
    if event:
        event.preventDefault()

    db = ServerData()

    clear_errors(["username", "email", "password", "confirm-password"])

    username = web.page["username"].value
    email = web.page["email"].value
    password = web.page["password"].value
    confirm_password = web.page["confirm-password"].value

    has_error = False

    if not username:
        show_feedback("username", "username-error", "Username is required.")
        has_error = True

    is_email_valid, email_err = validate_email(email)
    if not is_email_valid:
        show_feedback("email", "email-error", email_err)
        has_error = True

    is_pass_valid, pass_err = validate_password(password)
    if not is_pass_valid:
        show_feedback("password", "password-error", pass_err)
        has_error = True

    if password != confirm_password:
        show_feedback("confirm-password", "confirm-password-error", "Passwords do not match.")
        has_error = True

    if has_error:
        return

    try:
        success, message = await db.register_user(username, email, password)
        
        if success:
            await show_snackbar("Account Created! Enter your verification code.")
            encoded_email = window.encodeURIComponent(email)
            window.location.href = f"verify.html?email={encoded_email}"
        else:
            show_feedback("email", "email-error", message)
            
    except Exception as err:
        print(f"Unhandled Signup Error: {err}")
        await show_snackbar(f"Error: {err}")

@when("click", "#toggle-password")
def handle_password_toggle(event):
    toggle_password_mask("password", "eye-icon", "eye-off-icon")

@when("click", "#toggle-confirm-password")
def handle_confirm_password_toggle(event):
    toggle_password_mask("confirm-password", "confirm-eye-icon", "confirm-eye-off-icon")