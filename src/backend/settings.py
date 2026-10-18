import asyncio
from pyscript import document, window, when  # type: ignore
from server_data import ServerData
from auth import show_feedback, clear_errors, show_snackbar, validate_email, validate_password

server = ServerData()

def _toggle_password_visibility(input_selector):
    """Show/hide a password field (this page uses one emoji button, not eye icons)."""
    field = document.querySelector(input_selector)
    if field:
        field.type = "text" if field.type == "password" else "password"

def _init_settings():
    try:
        url_params = window.URLSearchParams.new(window.location.search)
        if url_params.has("verify_email"):
            token = url_params.get("verify_email")
            asyncio.ensure_future(_handle_verification(token))
    except Exception:
        pass
    asyncio.ensure_future(_load_settings())

async def _load_settings():
    success, data = await server.get_account_settings()
    # The payload is a dict on success and a message on failure, so the
    # isinstance check keeps a malformed body away from the .get() calls below.
    if not success or not isinstance(data, dict):
        asyncio.ensure_future(show_snackbar(str(data), 3))
        return
    
    document.querySelector("#user-display-name").textContent = data.get("username", "User")
    document.querySelector("#display-name").value = data.get("username", "")
    document.querySelector("#current-email-display").textContent = data.get("email", "")
    
    photo = data.get("profile_photo")
    if photo:
        document.querySelector("#settings-avatar-preview").src = photo

    pending = data.get("pending_email")
    if pending:
        p_el = document.querySelector("#pending-email-info")
        p_el.textContent = f"Pending: {pending} (check your inbox to confirm)"
        p_el.style.display = "block"

async def _handle_verification(token):
    success, data = await server.verify_email_change(token)
    if success and isinstance(data, dict):
        asyncio.ensure_future(show_snackbar(f"Email successfully verified to {data.get('email')}!", 4))
    else:
        asyncio.ensure_future(show_snackbar(str(data), 4))
    try:
        url = window.location.pathname
        window.history.replaceState({}, "", url)
    except Exception:
        pass
    await _load_settings()

def _pending_photo() -> str | None:
    """The photo the user picked: a data URL, "" to remove it, or None for no change.

    The file input handler in settings.html writes the cropped image into the
    hidden #avatar-pending-value field rather than announcing it with a custom
    event: the choice has to survive until Save is pressed, and reading a plain
    input keeps it a Python string that the JSON body can carry.
    """
    field = document.querySelector("#avatar-pending-value")
    if field is None:
        return None
    value = (field.value or "").strip()
    if not value:
        return None
    return "" if value == "remove" else value


@when("click", "#save-profile-btn")
async def handle_save_profile(event):
    clear_errors(["#display-name"])
    uname = document.querySelector("#display-name").value.strip()
    if not uname:
        show_feedback("#display-name", "#display-name-error", "Display name cannot be empty.")
        return
    
    kwargs = {"username": uname}
    photo = _pending_photo()
    if photo is not None:
        kwargs["profile_photo"] = photo

    success, data = await server.update_profile(**kwargs)
    if success:
        asyncio.ensure_future(show_snackbar("Profile updated successfully.", 3))
        # The choice is saved now, so a later save should not send it again.
        saved = document.querySelector("#avatar-pending-value")
        if saved is not None:
            saved.value = ""
        await _load_settings()
        # update topbar profile
        from topbar import render_user_profile
        # re-fetch settings or call render_user_profile with updated data
        _, sdata = await server.get_account_settings()
        if isinstance(sdata, dict):
            render_user_profile(sdata)
    else:
        show_feedback("#display-name", "#display-name-error", data)

@when("click", "#change-email-btn")
async def handle_change_email(event):
    clear_errors(["#new-email", "#email-change-password"])
    new_email = document.querySelector("#new-email").value.strip()
    password_input = document.querySelector("#email-change-password")
    current_password = password_input.value if password_input is not None else ""
    email_ok, email_err = validate_email(new_email)
    if not email_ok:
        show_feedback("#new-email", "#new-email-error", email_err)
        return
    if not current_password:
        # The server requires it: it is what proves this is the account holder and
        # not somebody who guessed the id in the URL.
        show_feedback("#email-change-password", "#email-change-password-error",
                      "Enter your current password to change your email.")
        return

    success, data = await server.request_email_change(new_email, current_password)
    if success:
        # The server answers 200 once the pending change is stored, but the mail
        # itself can fail (no mail credentials configured, or Brevo refusing a
        # send). Saying "sent" then leaves the user waiting for a message that
        # will never arrive.
        if isinstance(data, dict) and data.get("email_sent") is False:
            show_feedback(
                "#new-email", "#new-email-error",
                "The change was saved, but the confirmation email could not be sent. "
                "Please try again in a few minutes."
            )
        else:
            asyncio.ensure_future(show_snackbar("Verification email sent. Check your inbox.", 4))
        document.querySelector("#new-email").value = ""
        if password_input is not None:
            password_input.value = ""
        await _load_settings()
    else:
        show_feedback("#new-email", "#new-email-error", data)

@when("click", "#toggle-current-password")
def handle_toggle_current_pw(event):
    _toggle_password_visibility("#current-password")

@when("click", "#toggle-new-password")
def handle_toggle_new_pw(event):
    _toggle_password_visibility("#new-password")

@when("click", "#toggle-confirm-password")
def handle_toggle_confirm_pw(event):
    _toggle_password_visibility("#confirm-new-password")

@when("click", "#change-password-btn")
async def handle_change_password(event):
    clear_errors(["#current-password", "#new-password", "#confirm-new-password"])
    curr_pw = document.querySelector("#current-password").value
    new_pw = document.querySelector("#new-password").value
    conf_pw = document.querySelector("#confirm-new-password").value

    valid = True
    if not curr_pw:
        show_feedback("#current-password", "#current-password-error", "Current password is required.")
        valid = False
    pw_ok, pw_err = validate_password(new_pw)
    if not pw_ok:
        show_feedback("#new-password", "#new-password-error", pw_err)
        valid = False
    if new_pw != conf_pw:
        show_feedback("#confirm-new-password", "#confirm-new-password-error", "Passwords do not match.")
        valid = False
    if curr_pw and new_pw and curr_pw == new_pw:
        show_feedback("#new-password", "#new-password-error", "New password must be different from current password.")
        valid = False

    if not valid:
        return

    success, data = await server.change_password(curr_pw, new_pw)
    if success:
        asyncio.ensure_future(show_snackbar("Password updated successfully.", 3))
        document.querySelector("#current-password").value = ""
        document.querySelector("#new-password").value = ""
        document.querySelector("#confirm-new-password").value = ""
    else:
        show_feedback("#current-password", "#current-password-error", data)

@when("click", "#delete-account-btn")
def handle_open_delete_modal(event):
    document.querySelector("#delete-account-modal").style.display = "flex"
    document.querySelector("#delete-password").value = ""
    document.querySelector("#delete-confirm-phrase").value = ""
    document.querySelector("#confirm-delete-btn").disabled = True
    clear_errors(["#delete-password"])

@when("click", "#cancel-delete-btn")
def handle_close_delete_modal(event):
    document.querySelector("#delete-account-modal").style.display = "none"

@when("input", "#delete-confirm-phrase")
def handle_delete_phrase_input(event):
    phrase = document.querySelector("#delete-confirm-phrase").value
    btn = document.querySelector("#confirm-delete-btn")
    btn.disabled = (phrase != "DELETE")

@when("click", "#confirm-delete-btn")
async def handle_confirm_delete(event):
    clear_errors(["#delete-password"])
    pw = document.querySelector("#delete-password").value
    if not pw:
        show_feedback("#delete-password", "#delete-password-error", "Password is required.")
        return

    success, data = await server.delete_account(pw)
    if success:
        window.sessionStorage.setItem("account_deleted_message", "Your account has been deleted.")
        window.location.replace("login.html")
    else:
        show_feedback("#delete-password", "#delete-password-error", data)

_init_settings()