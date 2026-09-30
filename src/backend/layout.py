import sys
import asyncio
from server_data import ServerData

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window  # type: ignore
from auth import show_snackbar

import topbar

# --- TOGGLE SIDEBAR ---
@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    sidebar = web.page["#sidebar"]
    if sidebar:
        if "collapsed" in sidebar.classes:
            sidebar.classes.remove("collapsed")
        else:
            sidebar.classes.add("collapsed")

@when("click", "#create-project-btn")
def on_create_project_clicked(event):
    window.location.replace("create-project.html")