import sys
import asyncio

from models import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window # type: ignore
from auth import show_snackbar

def validate_session():
    db = ServerData()
    if db.get_active_session() is None:
        window.location.href = "login.html"
        return
    else:
        return

# --- 1. TOGGLE PROFILE DROPDOWN MENU ---
@when("click", "#profile-menu-btn")
def toggle_profile_dropdown(event):
    # Prevent click from immediately closing the dropdown via global click listener
    if event:
        event.stopPropagation()

    dropdown = web.page["profile-dropdown"]
    if dropdown is not None:
        dropdown.classList.toggle("hidden")


# --- 2. CLOSE DROPDOWN WHEN CLICKING OUTSIDE ---
@when("click", "body")
def close_dropdown_on_outside_click(event):
    dropdown = web.page["profile-dropdown"]
    if dropdown is not None and not dropdown.classList.contains("hidden"):
        dropdown.classList.add("hidden")


# --- 3. HANDLE SIGN OUT ---
@when("click", "#signout-btn")
async def handle_signout(event):
    if event:
        event.stopPropagation()

    # Hide dropdown menu immediately
    dropdown = web.page["profile-dropdown"]
    if dropdown is not None:
        dropdown.classList.add("hidden")

    # (Optional) Perform any session cleanup/token clearing here
    db = ServerData()
    db.clear_session()
    
    # Notify user and redirect to login page
    await show_snackbar("Signing out...")
    window.location.href = "login.html"

# --- 4. TOGGLE SIDEBAR (COLLAPSE / EXPAND) ---
@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    sidebar = web.page["sidebar"]
    if sidebar is not None:
        sidebar.classList.toggle("collapsed")

validate_session()

@when("click", "#create-project-btn")
def handle_create_project(event):
    window.location.href = "create-project.html"