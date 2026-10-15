import sys
import asyncio
from html import escape

import js
from pyodide.ffi import create_proxy
from pyscript import window, web, when, document  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

# `auth` and `dialog` are loaded by their flat names via settings.json's file
# map (src/backend/utils/auth.py -> ./auth.py), so Pylance cannot resolve them
# from this folder; the ignores keep those runtime-correct imports quiet.
from auth import show_snackbar  # type: ignore
from dialog import confirm_action  # type: ignore
from project_role_helpers import permissions_for_user  # type: ignore
from server_data import ServerData, Project
from project_helpers import get_project_id_from_url # type: ignore
from auth import show_snackbar

# Set once the project has loaded; used by the End Project button.
_db = None
_project_id = None


def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    project_id = params.get("project_id")
    if project_id and project_id.isdigit():
        return int(project_id)
    return None


def apply_status(status: str):
    """Updates the status badge and End Project button to match the status."""
    status = str(status).lower()
    badge = document.getElementById("project-status-badge")
    if badge is not None:
        badge.textContent = status.capitalize()
        badge.className = f"status-badge status-{status}"

    end_btn = document.getElementById("end-project-btn")
    if end_btn is not None:
        completed = status == "completed"
        end_btn.textContent = "Project Ended" if completed else "End Project"
        end_btn.disabled = completed


async def handle_end_project():
    """Marks the project Completed after confirmation. This cannot be undone."""
    if _db is None or _project_id is None:
        return
    if not window.confirm(
        "End this project? It will be marked Completed and cannot be reopened."
    ):
        return

    success, err = await _db.update_project_status(_project_id, "completed")
    if not success:
        await show_snackbar(f"Failed to end project: {err}")
        return

    apply_status("completed")
    await show_snackbar("Project ended. It is now marked Completed.")


def _on_end_project_click(event):
    asyncio.ensure_future(handle_end_project())


end_project_proxy = create_proxy(_on_end_project_click)


# Delete Project lives in this page's sidebar footer. These hold what the click
# handler needs: which project the page is showing, and whether the signed-in
# user is allowed to delete it at all.
_project_id = None
_can_delete = False


def _reveal_delete_control(permissions):
    """Offer Delete Project to a role holding delete_project, nobody else.

    The same permission the DELETE /projects/{id} route enforces, so this only
    stops the page from presenting an action that would come back as a 403.
    """
    global _can_delete
    _can_delete = "delete_project" in permissions

    button = web.page["#delete-project-btn"]
    if button is None:
        return
    if _can_delete:
        button.classList.remove("hidden")
    else:
        button.classList.add("hidden")


def load_default_view(project: Project):
    content_el = web.page["#project-view-content"]
    # Both values are project input, so they are escaped before they are placed
    # into innerHTML, the same as every other value a page renders.
    name = escape(project.name or "")
    description = escape(project.description or "There is no description for this project.")

    if content_el:
        content_el.innerHTML = f"""
            <div class="content-header">
                <div class="project-title-group">
                    <h1 class="page-title">{escape(str(project.name))}</h1>
                    <span id="project-status-badge" class="status-badge status-active">Active</span>
                </div>
                <button type="button" id="end-project-btn" class="btn-end-project">End Project</button>
            </div>
            <div class="project-details-card" style="background:#fff; padding:24px; border-radius:8px; border:1px solid #e0e0e0;">
                <h2 style="margin-bottom:12px; font-size:18px;">Project Description</h2>
                <p style="color:#555; line-height:1.6;">{escape(str(description))}</p>
            </div>
        """
        # The button is created dynamically, so attach the listener directly.
        document.getElementById("end-project-btn").addEventListener("click", end_project_proxy)
        apply_status(project.status)


async def init_project_page():
    global _project_id

    project_id = get_project_id_from_url()
    _project_id = project_id

    if not project_id:
        window.location.href = "dashboard.html"
        return

    global _db
    db = ServerData()
    project = await db.get_project_by_id(project_id)

    # CHANGE: removed the simple member roster that used to render here
    # (load_members_view, _initials and the ?view=members branch). Members now have
    # their own page, project-members.html, which the sidebar Members button opens.
    # This page only ever renders the description.
    if project:
        _db = db
        _project_id = project_id
        load_default_view(project)
        # One extra read decides whether the sidebar offers Delete Project. It is
        # the members payload (roles + role definitions), which is what
        # permissions_for_user() reads; get_project_by_id() carries no role map.
        members_payload = await db.get_project_members(project_id)
        _reveal_delete_control(
            permissions_for_user(members_payload, db.get_active_session())
        )
    else:
        content_el = web.page["#project-view-content"]
        if content_el:
            content_el.innerHTML = """
                <div class="content-header">
                    <h1 class="page-title">Access Denied or Project Not Found</h1>
                </div>
            """


@when("click", "#delete-project-btn")
async def handle_delete_project(event):
    """Confirm, delete this project, then return to the dashboard.

    Bound with @when rather than a raw create_proxy(): the decorator registers a
    synchronous event handler, so this async function is scheduled by PyScript
    itself and the button has no competing card-level navigation to lose to.
    """
    if not _project_id or not _can_delete:
        return

    db = ServerData()
    project = await db.get_project_by_id(_project_id)
    name = getattr(project, "name", None) or f"project {_project_id}"

    confirmed, _password = await confirm_action(title=f"Delete project {name}")
    if not confirmed:
        return

    success, message = await db.delete_project(_project_id)
    if not success:
        # Keep the page (and the button) so the failure can be read and retried.
        await show_snackbar(message)
        return

    # Nothing is left on this page to return to, so go back to the dashboard.
    window.location.href = "dashboard.html"


# Launch the async initialization process
asyncio.ensure_future(init_project_page())