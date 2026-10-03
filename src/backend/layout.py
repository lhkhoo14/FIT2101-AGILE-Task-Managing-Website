import sys
import asyncio
from server_data import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window  # type: ignore
from auth import show_snackbar

import topbar

def validate_session():
    if not window.localStorage.getItem("session_user_id"):
        window.location.href = "login.html"

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
    sidebar = web.page["#sidebar"]
    if sidebar:
        if "collapsed" in sidebar.classes:
            sidebar.classes.remove("collapsed")
        else:
            sidebar.classes.add("collapsed")