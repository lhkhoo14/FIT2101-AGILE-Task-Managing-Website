import sys
import html
import asyncio
import js  # type: ignore
from pyscript import window, web, document, when  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData, Project
current_project = None


def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    project_id = params.get("project_id")
    if project_id and project_id.isdigit():
        return int(project_id)
    return None


def load_default_view(project: Project):
    global current_project
    current_project = project

    content_el = web.page["#project-view-content"]

    description = html.escape(
        project.description or "There is no description for this project."
    )
    project_name = html.escape(project.name or "Untitled Project")
    last_edited_by = html.escape(project.last_edited_by or "")
    last_edited_at = html.escape(project.last_edited_at or "")

    audit_html = ""

    if last_edited_by and last_edited_at:
        audit_html = f"""
            <p style="color:#777; font-size:13px; margin-top:20px;">
                Last edited by {last_edited_by}
                on {last_edited_at}
            </p>
        """

    if content_el:
        content_el.innerHTML = f"""
            <div class="content-header">
                <h1 class="page-title">{project_name}</h1>
            </div>

            <div id="project-description-card"
                 style="background:#fff; padding:24px;
                 border-radius:8px; border:1px solid #e0e0e0;">

                <h2 style="margin-bottom:12px; font-size:18px;">
                    Project Description
                </h2>

                <p style="color:#555; line-height:1.6;">
                    {description}
                </p>

                {audit_html}

                <button id="edit-description-btn">
                    Edit Description
                </button>
            </div>
        """

@when("click", "#project-view-content")
async def handle_project_view_click(event):
    button = event.target.closest("button")

    if not button:
        return

    if button.id == "edit-description-btn":
        content_el = web.page["#project-description-card"]

        if current_project is None or not content_el:
            return

        description = html.escape(
            current_project.description or ""
        )

        content_el.innerHTML = f"""
            <h2 style="margin-bottom:12px; font-size:18px;">
                Edit Project Description
            </h2>

            <textarea id="description-input"
                      rows="6"
                      style="width:100%; box-sizing:border-box;">{description}</textarea>

            <div style="margin-top:12px;">
                <button id="save-description-btn">Save</button>
                <button id="cancel-description-btn">Cancel</button>
            </div>

            <p id="description-error" style="color:red;"></p>
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
                error_element.textContent = (
                    "Description cannot be empty."
                )
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

        project = await db.get_project_by_id(project_id)

        if project:
            load_default_view(project)

async def init_project_page():
    project_id = get_project_id_from_url()

    if not project_id:
        window.location.href = "dashboard.html"
        return

    db = ServerData()
    # Fixed: Added 'await' to resolve the coroutine
    project = await db.get_project_by_id(project_id)

    if project:
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