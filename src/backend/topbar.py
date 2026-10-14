import sys
import asyncio
from server_data import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar

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
    if user.get("profile_photo") and not str(user.get("profile_photo")).endswith("default-profile.svg"):
        profile_btn = document.querySelector("#profile-menu-btn .profile-avatar")
        if profile_btn:
            img = document.createElement("img")
            img.className = "profile-avatar-img"
            img.src = user.get("profile_photo")
            profile_btn.innerHTML = ""
            profile_btn.appendChild(img)

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

async def init_topbar():
    server_data = ServerData()
    current_user = await guard_session(server_data)

    if current_user:
        # Update UI elements with logged-in user details if present
        render_user_profile(current_user)

@when("click", ".brand-title")
def handle_brand_home_click(event):
    """Brand title button to return to main dashboard."""
    window.location.href = "dashboard.html"

asyncio.ensure_future(init_topbar())

# --- 4. OPEN SETTINGS PAGE ---
@when("click", "#settings-btn")
def handle_open_settings(event):
    try:
        window.top.location.href = "settings.html"
    except Exception:
        window.location.href = "settings.html"