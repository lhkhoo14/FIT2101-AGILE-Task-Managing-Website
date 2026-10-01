import json

from pyscript import when, web, window  # type: ignore
from constants import API_URL
from server_data import ServerData
from auth import show_snackbar

def show_error(field_id: str, message: str):
    """Displays an error message underneath a form field."""

    error = web.page[f"#{field_id}-error"]

    if error is not None:
        error.innerText = message
        error.classList.add("show")

def clear_errors():
    """Clears all project creation errors."""

    for field_id in ["project-name", "project-description"]:
        error = web.page[f"#{field_id}-error"]

        if error is not None:
            error.innerText = ""
            error.classList.remove("show")

@when("submit", "#create-project-form")
async def create_project(event):
    """Handles project form submission."""
    if event:
        event.preventDefault()

    clear_errors()

    name = web.page["#project-name"].value.strip()
    description = web.page["#project-description"].value.strip()

    # Form Validation
    if not name:
        show_error("project-name", "Project name is required.")
        return

    # Check Active Session via ServerData
    db = ServerData()

    if db.get_active_session() is None:
        window.location.replace("login.html")
        return

    # API Request via ServerData
    success, error_message, project_id = await db.create_project(name, description)

    if success and project_id:
        await show_snackbar("Project created successfully!")
        window.location.replace(f"project-page.html?project_id={project_id}")
    else:
        show_error("project-name", error_message)
        await show_snackbar(error_message)


@when("click", "#cancel-project")
def cancel_project(event):
    """Returns the user to the dashboard without creating a project."""

    window.location.href = "dashboard.html"