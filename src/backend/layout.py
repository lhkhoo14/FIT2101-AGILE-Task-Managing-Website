import sys

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web  # type: ignore

import topbar

# CHANGE: removed this module's own copies of the profile-dropdown, outside-click
# and sign-out handlers. topbar already owns them and is imported below, so both
# sets registered and a single click toggled the dropdown twice - opening it and
# instantly closing it again, which made the avatar look dead on the dashboard and
# sprint pages. Only the sidebar toggle belongs here now.

# --- TOGGLE SIDEBAR (COLLAPSE / EXPAND) ---
@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    sidebar = web.page["#sidebar"]
    if sidebar:
        if "collapsed" in sidebar.classes:
            sidebar.classes.remove("collapsed")
        else:
            sidebar.classes.add("collapsed")