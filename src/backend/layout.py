import sys

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when  # type: ignore

import topbar
import sidebar_state

# CHANGE: removed this module's own copies of the profile-dropdown, outside-click
# and sign-out handlers. topbar already owns them and is imported below, so both
# sets registered and a single click toggled the dropdown twice - opening it and
# instantly closing it again, which made the avatar look dead on the dashboard and
# sprint pages. Only the sidebar toggle belongs here now.

# --- TOGGLE SIDEBAR (COLLAPSE / EXPAND) ---
@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    # US-17: the toolbar button is the only thing that collapses the rail, and
    # the choice is remembered for the rest of the browser session by
    # sidebar_state, so navigating between pages does not reset it.
    try:
        sidebar_state.toggle()
    except Exception as exc:
        print(f"[Sidebar] Could not toggle the rail: {exc}")


# US-17: apply whatever the user chose earlier in this session on page load.
try:
    sidebar_state.restore()
except Exception as exc:
    print(f"[Sidebar] Preference not applied: {exc}")