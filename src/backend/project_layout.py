import sys
import js  # type: ignore
from pyscript import when, web, window  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

# Import decoupled topbar module
import topbar

def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    return params.get("project_id")


def _highlight_active_nav():
    # The page reloads per view, so the nav item matching ?view= is marked here.
    view = js.URLSearchParams.new(window.location.search).get("view")
    active_id = "#nav-members" if view == "members" else "#nav-description"
    for nav_id in ("#nav-description", "#nav-members"):
        item = web.page[nav_id]
        if item is None:
            continue
        if nav_id == active_id:
            item.classList.add("active")
        else:
            item.classList.remove("active")


def init_project_layout():
    project_id = get_project_id_from_url()
    project_name_el = web.page["#project-name-display"]
    if project_name_el and project_id:
        project_name_el.textContent = f"Project {project_id}"
    _highlight_active_nav()

@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    # Retrieve either project-sidebar or standard dashboard sidebar
    sidebar = web.page["#project-sidebar"] or web.page["#sidebar"]
    if sidebar:
        if "collapsed" in sidebar.classes:
            sidebar.classes.remove("collapsed")
        else:
            sidebar.classes.add("collapsed")

# --- PROJECT NAVIGATION HANDLERS ---
@when("click", "#nav-description")
def handle_nav_description(event):
    project_id = get_project_id_from_url()
    window.location.href = f"project-page.html?project_id={project_id}"

@when("click", "#nav-members")
def handle_nav_members(event):
    project_id = get_project_id_from_url()
    window.location.href = f"project-page.html?project_id={project_id}&view=members"

@when("click", "#nav-sprints")
def handle_nav_sprints(event):
    project_id = get_project_id_from_url()
    window.location.href = f"sprint-dashboard.html?project_id={project_id}"

# Initialize project view layout
init_project_layout()