import sys
import js  # type: ignore
from pyscript import when, web, window  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

# Import decoupled topbar module
import topbar
import sidebar_state

def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    return params.get("project_id")


# CHANGE: project_layout.py is shared by three project views, each of which
# ships a different nav item already marked "active" in its own markup.
_NAV_ITEMS = ("#nav-description", "#nav-members", "#nav-sprints")

_ACTIVE_NAV_BY_PAGE = {
    "project-page.html": "#nav-description",
    "project-members.html": "#nav-members",
    "sprint-dashboard.html": "#nav-sprints",
}


def _highlight_active_nav():
    # CHANGE: bug fix. This module is loaded by project-page.html,
    # project-members.html AND sprint-dashboard.html. The old code unconditionally
    # added "active" to #nav-description, so on the Members and Sprints tabs two
    # buttons were lit at once and Description looked selected no matter which
    # view was open.
    #
    # The active item is now taken from the page being viewed: every nav item is
    # cleared first, then exactly one is marked, so the sidebar always matches the
    # content on screen. Unrecognised pages are left alone rather than guessed at.
    path = str(window.location.pathname or "").lower()

    active_id = next(
        (nav_id for page, nav_id in _ACTIVE_NAV_BY_PAGE.items() if page in path),
        None,
    )

    if active_id is None:
        return

    for nav_id in _NAV_ITEMS:
        item = web.page[nav_id]
        if item is not None:
            item.classList.remove("active")

    active_item = web.page[active_id]
    if active_item is not None:
        active_item.classList.add("active")


def init_project_layout():
    project_id = get_project_id_from_url()
    project_name_el = web.page["#project-name-display"]
    if project_name_el and project_id:
        project_name_el.textContent = f"Project {project_id}"
    # US-17: re-apply the collapse choice the user made earlier in this session
    # before the first paint of the rail, so switching between the project views
    # never looks like the navigation reset itself.
    try:
        sidebar_state.restore()
    except Exception as exc:
        print(f"[Sidebar] Preference not applied: {exc}")
    _highlight_active_nav()

@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    # US-17: the toolbar button is the only thing that collapses the rail, and
    # the choice is stored for the rest of the browser session.
    try:
        sidebar_state.toggle()
    except Exception as exc:
        print(f"[Sidebar] Could not toggle the rail: {exc}")

# --- PROJECT NAVIGATION HANDLERS ---
@when("click", "#nav-projects")
def handle_nav_projects(event):
    # Back to the project dashboard (all projects).
    window.location.href = "dashboard.html"

@when("click", "#nav-description")
def handle_nav_description(event):
    project_id = get_project_id_from_url()
    window.location.href = f"project-page.html?project_id={project_id}"

@when("click", "#nav-members")
def handle_nav_members(event):
    # CHANGE: was project-page.html?view=members, which rendered the simple roster
    # on this page. Members now have their own page, so the sidebar button opens it.
    project_id = get_project_id_from_url()
    window.location.href = f"project-members.html?project_id={project_id}"

@when("click", "#nav-sprints")
def handle_nav_sprints(event):
    project_id = get_project_id_from_url()
    window.location.href = f"sprint-dashboard.html?project_id={project_id}"

# Initialize project view layout
init_project_layout()