import sys
import asyncio
from html import escape

import js  # type: ignore
from pyodide.ffi import create_proxy  # type: ignore
from pyscript import window, web, when, document  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

# PyScript loads these by their flat names through settings.json's file map
# (src/backend/utils/auth.py -> ./auth.py), which is also why pyrightconfig.json
# lists these two folders under extraPaths: it lets the editor resolve the same
# names. The ignores stay because they are what the browser actually does.
from auth import show_snackbar  # type: ignore
from server_data import ServerData, Project  # type: ignore

# get_project_id_from_url() is defined in this module below: it reads the id out
# of window.location.search, which project_helpers' copy does not. The import of
# that copy was shadowed by the local definition and has been dropped.

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


# Delete Project is handled by project_layout.py, which every project view loads.


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
    else:
        content_el = web.page["#project-view-content"]
        if content_el:
            content_el.innerHTML = """
                <div class="content-header">
                    <h1 class="page-title">Access Denied or Project Not Found</h1>
                </div>
            """


# Launch the async initialization process
asyncio.ensure_future(init_project_page())