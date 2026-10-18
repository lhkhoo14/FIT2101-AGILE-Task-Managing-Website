import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window  # type: ignore
from server_data import ServerData
from auth import (  # type: ignore
    validate_email,
    validate_password,
    clear_errors,
    show_feedback,
    show_snackbar,
    toggle_password_mask,
)

@when("click", "#send-code-btn")
async def handle_send_code(event):
    if event:
        event.preventDefault()

    clear_errors(["email"])

    email = web.page["#email"].value.strip()
    is_valid, err_msg = validate_email(email)
    if not is_valid:
        show_feedback("email", "email-error", err_msg)
        return

    db = ServerData()
    success, message = await db.request_password_reset(email)

    if success:
        await show_snackbar(message)
        
        # Reveal the code and password reset fields progressively
        reset_container = web.page["#reset-fields-container"]
        if reset_container:
            reset_container.classes.remove("hidden")

        # Start 60-second cooldown UI on the send code button
        send_btn = web.page["#send-code-btn"]
        send_btn.disabled = True
        for remaining in range(60, 0, -1):
            send_btn.innerText = f"Resend ({remaining}s)"
            await asyncio.sleep(1)
        send_btn.disabled = False
        send_btn.innerText = "Send Code"
    else:
        show_feedback("email", "email-error", message)


@when("submit", "#forgot-password-form")
async def handle_reset_password(event):
    if event:
        event.preventDefault()

    clear_errors(["email", "verification-code", "new-password", "confirm-password"])

    email = web.page["#email"].value.strip()
    code = web.page["#verification-code"].value.strip().upper()
    password = web.page["#new-password"].value
    confirm_password = web.page["#confirm-password"].value

    has_error = False

    if not email:
        show_feedback("email", "email-error", "Email is required.")
        has_error = True

    if not code or len(code) != 6:
        show_feedback("verification-code", "code-error", "Enter a valid 6-character code.")
        has_error = True

    is_pass_valid, pass_err = validate_password(password)
    if not is_pass_valid:
        show_feedback("new-password", "password-error", pass_err)
        has_error = True

    if password != confirm_password:
        show_feedback("confirm-password", "confirm-password-error", "Passwords do not match.")
        has_error = True

    if has_error:
        return

    db = ServerData()
    success, message = await db.reset_password(email, code, password)

    if success:
        await show_snackbar(message)
        await asyncio.sleep(1.5)
        window.location.replace("login.html")
    else:
        show_feedback("verification-code", "code-error", message)


@when("click", "#toggle-password")
def handle_password_toggle(event):
    toggle_password_mask("new-password", "eye-icon", "eye-off-icon")


@when("click", "#toggle-confirm-password")
def handle_confirm_password_toggle(event):
    toggle_password_mask("confirm-password", "confirm-eye-icon", "confirm-eye-off-icon")