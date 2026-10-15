import sys
import asyncio
from server_data import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from pyodide.ffi import create_proxy  # type: ignore
from auth import show_snackbar
from dialog import confirm_action

# --- 1. TOGGLE PROFILE DROPDOWN MENU ---
@when("click", "#profile-menu-btn")
def toggle_profile_dropdown(event):
    if event:
        event.stopPropagation()

    dropdown = web.page["#profile-dropdown"]
    if dropdown:
        if "hidden" in dropdown.classes:
            dropdown.classes.remove("hidden")
        else:
            dropdown.classes.add("hidden")

# --- 2. CLOSE DROPDOWN WHEN CLICKING OUTSIDE ---
@when("click", "body")
def close_dropdown_on_outside_click(event):
    dropdown = web.page["#profile-dropdown"]
    if dropdown and "hidden" not in dropdown.classes:
        dropdown.classes.add("hidden")

# --- 3. HANDLE SIGN OUT ---
@when("click", "#signout-btn")
async def handle_signout(event):
    if event:
        event.stopPropagation()

    dropdown = web.page["#profile-dropdown"]
    if dropdown:
        dropdown.classes.add("hidden")

    db = ServerData()
    db.clear_session()
    
    await show_snackbar("Signing out...")
    window.location.replace("login.html")

def render_user_profile(user: dict):
    name_elem = web.page["#user-display-name"]
    email_elem = web.page["#user-display-email"]

    if name_elem:
        name_elem.innerText = user.get("username", "Username")
    if email_elem:
        email_elem.innerText = user.get("email", "Email")

async def guard_session(server_data: ServerData) -> dict | None:
    """Validates session asynchronously against FastAPI backend."""
    session_id = server_data.get_active_session()

    if session_id is None:
        window.location.replace("login.html")
        return None

    # Query FastAPI endpoint for user details
    user = await server_data.get_user_by_id(session_id)
    if user is None:
        print("[Auth Guard] Invalid session or user not found. Redirecting...")
        server_data.clear_session()
        window.location.replace("login.html")
        return None

    return user

async def handle_delete_account(event):
    """Delete the signed-in account, once the owner confirms with its password."""
    event.stopPropagation()

    dropdown = web.page["#profile-dropdown"]
    if dropdown:
        dropdown.classes.add("hidden")

    confirmed, password = await confirm_action(
        title="Delete my account",
        require_password=True
    )
    if not confirmed:
        return
    if not password:
        await show_snackbar("Enter your password to confirm.")
        return

    db = ServerData()
    success, message = await db.delete_account(password)
    await show_snackbar(message)

    if success:
        db.clear_session()
        window.location.replace("login.html")

# Created once and kept, so the callback cannot be garbage collected.
_delete_account_proxy = create_proxy(handle_delete_account)


def add_delete_account_item():
    """Add the self-service account deletion entry to the profile dropdown.

    Injected from here rather than written into every page's copy of the top bar,
    and only once the session guard has confirmed somebody is signed in.
    """
    dropdown = web.page["#profile-dropdown"]
    if not dropdown or web.page["#delete-account-btn"]:
        return

    button = document.createElement("button")
    button.id = "delete-account-btn"
    button.type = "button"
    button.className = "dropdown-item"
    button.innerText = "Delete Account"
    button.addEventListener("click", _delete_account_proxy)
    dropdown.appendChild(button)


async def init_topbar():
    server_data = ServerData()
    current_user = await guard_session(server_data)

    if current_user:
        # Update UI elements with logged-in user details if present
        render_user_profile(current_user)
        add_delete_account_item()

@when("click", ".brand-title")
def handle_brand_home_click(event):
    """Brand title button to return to main dashboard."""
    window.location.href = "dashboard.html"

asyncio.ensure_future(init_topbar())