import asyncio
import sys
import os
import js  # type: ignore
from pyscript import when, web, window  # type: ignore

backend_path = os.path.abspath(os.path.join(os.path.dirname(__name__), ".."))
if "src/backend" not in sys.path:
    sys.path.append("src/backend")

# Import decoupled topbar module
import topbar
import sidebar_state
from project_helpers import get_project_id_from_url
from auth import show_snackbar
from dialog import confirm_action
from project_role_helpers import permissions_for_user
from server_data import ServerData

# CHANGE: project_layout.py is shared by three project views, each of which
# ships a different nav item already marked "active" in its own markup. Every
# item _ACTIVE_NAV_BY_PAGE can name has to appear here, otherwise the clearing
# loop below cannot un-light it and the "exactly one item is active" rule the
# code below promises quietly stops holding.
_NAV_ITEMS = ("#nav-description", "#nav-members", "#nav-roles", "#nav-sprints")

_ACTIVE_NAV_BY_PAGE = {
    "project-page.html": "#nav-description",
    "project-members.html": "#nav-members",
    "project-roles.html": "#nav-roles",
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
    # The rail used to write the project id into #project-name-display, an id no
    # page defines - and page[...] returns None for a missing id rather than
    # raising, so the line did nothing at all. Removed instead of guarded: the
    # project name has never been shown in the rail, and "Project 3" is the id,
    # not the name. Showing the real one means passing it in from each page
    # module, which already loads the project.
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

@when("click", "#nav-roles")
def handle_nav_roles(event):
    project_id = get_project_id_from_url()
    window.location.href = f"project-roles.html?project_id={project_id}"

@when("click", "#nav-sprints")
def handle_nav_sprints(event):
    project_id = get_project_id_from_url()
    window.location.href = f"sprint-dashboard.html?project_id={project_id}"

# Initialize project view layout
init_project_layout()

# --- DELETE PROJECT (shared by every project view) --------------------------
# The button sits in the sidebar footer of all four project pages, and every one
# of them loads this module, so the reveal and the click live here rather than
# only on the description view.
async def _reveal_delete_control():
    project_id = get_project_id_from_url()
    button = web.page["#delete-project-btn"]
    if project_id is None or button is None:
        return

    db = ServerData()
    # The members payload carries the role map and the role definitions, which is
    # what permissions_for_user() reads; the project itself carries no roles.
    members_payload = await db.get_project_members(project_id)
    if not members_payload:
        return
    if "delete_project" in permissions_for_user(members_payload, db.get_active_session()):
        button.classList.remove("hidden")


@when("click", "#delete-project-btn")
async def handle_delete_project(event):
    """Confirm, delete this project, then return to the dashboard."""
    project_id = get_project_id_from_url()
    if project_id is None:
        return

    db = ServerData()
    project = await db.get_project_by_id(project_id)
    name = getattr(project, "name", None) or f"project {project_id}"

    confirmed, _password = await confirm_action(title=f"Delete project {name}")
    if not confirmed:
        return

    success, message = await db.delete_project(project_id)
    if not success:
        # Keep the page (and the button) so the failure can be read and retried.
        await show_snackbar(message)
        return

    window.location.href = "dashboard.html"


asyncio.ensure_future(_reveal_delete_control())
