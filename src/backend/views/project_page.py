
import sys
import asyncio
import html

import js  # type: ignore
from pyodide.ffi import create_proxy  # type: ignore
from pyscript import window, web, when, document  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

from auth import show_snackbar  # type: ignore
from server_data import ServerData, Project  # type: ignore


_db = None
_project_id = None
current_project = None


def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    project_id = params.get("project_id")

    if project_id and project_id.isdigit():
        return int(project_id)

    return None


def apply_status(status: str):
    """Update the project status badge and End Project button."""
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
    """Mark the project as completed after confirmation."""
    if _db is None or _project_id is None:
        return

    if not window.confirm(
        "End this project? It will be marked Completed and cannot be reopened."
    ):
        return

    success, err = await _db.update_project_status(
        _project_id, "completed"
    )

    if not success:
        await show_snackbar(f"Failed to end project: {err}")
        return

    apply_status("completed")
    await show_snackbar("Project ended. It is now marked Completed.")


def _on_end_project_click(event):
    asyncio.ensure_future(handle_end_project())


end_project_proxy = create_proxy(_on_end_project_click)


def load_default_view(project: Project):
    """Display project details, audit metadata, and available actions."""
    global current_project
    current_project = project

    content_el = web.page["#project-view-content"]
    if not content_el:
        return

    name = html.escape(str(project.name or "Untitled Project"))
    description = html.escape(
        str(project.description or "There is no description for this project.")
    )
    last_edited_by = html.escape(str(project.last_edited_by or ""))
    last_edited_at = html.escape(str(project.last_edited_at or ""))

    audit_html = ""

    if last_edited_by and last_edited_at:
        audit_html = f"""
            <p class="project-audit-footer">
                Last edited by {last_edited_by} on {last_edited_at}
            </p>
        """

    content_el.innerHTML = f"""
        <div class="content-header">
            <div class="project-title-group">
                <h1 class="page-title">{name}</h1>
                <span id="project-status-badge"
                      class="status-badge status-active">Active</span>
            </div>
            <button type="button" id="end-project-btn"
                    class="btn-end-project">End Project</button>
        </div>

        <div id="project-description-card"
             class="project-details-card"
             style="background:#fff; padding:24px;
                    border-radius:8px; border:1px solid #e0e0e0;">

            <h2 style="margin-bottom:12px; font-size:18px;">
                Project Description
            </h2>

            <p class="project-description-text">
                {description}
            </p>

            {audit_html}

            <button type="button" id="edit-description-btn"
                    class="btn-edit-description">
                Edit Description
            </button>
        </div>
    """

    end_btn = document.getElementById("end-project-btn")
    if end_btn is not None:
        end_btn.addEventListener("click", end_project_proxy)

    apply_status(project.status)


@when("click", "#project-view-content")
async def handle_project_view_click(event):
    """Handle editing, saving, and cancelling the description."""
    button = event.target.closest("button")

    if not button:
        return

    if button.id == "edit-description-btn":
        if current_project is None:
            return

        description = html.escape(
            str(current_project.description or "")
        )

        content_el = web.page["#project-description-card"]
        if not content_el:
            return

        content_el.innerHTML = f"""
            <h2 style="margin-bottom:12px; font-size:18px;">
                Edit Project Description
            </h2>

            <textarea id="description-input"
                    class="project-description-input"
                    rows="6">{description}</textarea>

            <div style="margin-top:12px;">
                <button type="button" id="save-description-btn"
                        class="btn-save-description">Save</button>

            <button type="button" id="cancel-description-btn"
                        class="btn-cancel-description">Cancel</button>
        </div>

            <p id="description-error" class="project-description-error"></p>
        """

    elif button.id == "cancel-description-btn":
        if current_project is not None:
            load_default_view(current_project)

    elif button.id == "save-description-btn":
        project_id = get_project_id_from_url()
        description_input = web.page["#description-input"]
        error_element = web.page["#description-error"]

        if not project_id or not description_input:
            return

        new_description = description_input.value.strip()

        if not new_description:
            if error_element:
                error_element.textContent = "Description cannot be empty."
            return

        db = ServerData()

        success, message, data = await db.update_project_description(
            project_id,
            new_description
        )

        if not success:
            if error_element:
                error_element.textContent = message
            return

        updated_project = await db.get_project_by_id(project_id)

        if updated_project:
            load_default_view(updated_project)
            await show_snackbar("Project description updated successfully.")


async def init_project_page():
    global _db, _project_id

    project_id = get_project_id_from_url()
    _project_id = project_id

    if not project_id:
        window.location.href = "dashboard.html"
        return

    db = ServerData()
    project = await db.get_project_by_id(project_id)

    if project:
        _db = db
        load_default_view(project)
    else:
        content_el = web.page["#project-view-content"]
        if content_el:
            content_el.innerHTML = """
                <div class="content-header">
                    <h1 class="page-title">
                        Access Denied or Project Not Found
                    </h1>
                </div>
            """


asyncio.ensure_future(init_project_page())
