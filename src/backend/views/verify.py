import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window  # type: ignore
from server_data import ServerData
from auth import show_feedback, clear_errors, show_snackbar  # type: ignore

# Auto-fill email from URL parameters on page load
def init_verification_page():
    try:
        url_params = window.URLSearchParams.new(window.location.search)
        email_param = url_params.get("email")
        if email_param:
            email_input = web.page["#email"]
            if email_input:
                email_input.value = email_param
    except Exception as e:
        print(f"[Init Error] {e}")

init_verification_page()

@when("submit", "#verify-form")
async def handle_verify(event):
    if event:
        event.preventDefault()

    clear_errors(["email", "verification-code"])

    email = web.page["#email"].value.strip()
    code = web.page["#verification-code"].value.strip().upper()

    if not email:
        show_feedback("email", "email-error", "Email is required.")
        return
    if not code or len(code) != 6:
        show_feedback("verification-code", "code-error", "Enter a valid 6-character code.")
        return

    db = ServerData()
    success, message = await db.verify_user_code(email, code)

    if success:
        await show_snackbar("Account verified successfully! Redirecting...")
        await asyncio.sleep(1.5)
        window.location.replace("login.html")
    else:
        show_feedback("verification-code", "code-error", message)

@when("click", "#send-code-btn")
async def handle_resend(event):
    if event:
        event.preventDefault()

    clear_errors(["email"])
    email = web.page["#email"].value.strip()
    if not email:
        show_feedback("email", "email-error", "Enter your email first to resend code.")
        return

    db = ServerData()
    success, message = await db.resend_verification_code(email)

    if success:
        await show_snackbar(message)
        # Start 60-second cooldown UI
        send_btn = web.page["#send-code-btn"]
        send_btn.disabled = True
        for remaining in range(60, 0, -1):
            send_btn.innerText = f"Resend ({remaining}s)"
            await asyncio.sleep(1)
        send_btn.disabled = False
        send_btn.innerText = "Send Code"
    else:
        # Display the server error inline and via snackbar (e.g. "Account is already verified.")
        show_feedback("email", "email-error", message)
        await show_snackbar(message)