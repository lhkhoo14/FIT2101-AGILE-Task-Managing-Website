import json

from pyscript import when, web, window  # type: ignore


API_URL = "http://127.0.0.1:8000"


def get_current_user_id():
    """Gets the currently logged-in user's ID from the browser session."""

    user_id = window.localStorage.getItem("session_user_id")

    if user_id is None or user_id.strip() == "":
        return None

    return int(user_id)


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
    """Sends the new project details to the FastAPI backend."""

    if event:
        event.preventDefault()

    clear_errors()

    name = web.page["#project-name"].value.strip()
    description = web.page["#project-description"].value.strip()

    # Validate project name
    if not name:
        show_error("project-name", "Project name is required.")
        return

    # Validate project description
    if not description:
        show_error("project-description", "Project description is required.")
        return

    user_id = get_current_user_id()

    if user_id is None:
        window.location.href = "login.html"
        return

    payload = {
        "user_id": user_id,
        "name": name,
        "description": description
    }

    try:

        response = await window.fetch(
            f"{API_URL}/api/projects",
            {
                "method": "POST",
                "headers": {
                    "Content-Type": "application/json"
                },
                "body": json.dumps(payload)
            }
        )

        if response.ok:

            result = await response.json()

            print("Project created successfully:", result)

            # Return to dashboard after creating project
            window.location.href = "dashboard.html"

        else:

            error_data = await response.json()

            print("Project creation failed:", error_data)

            show_error(
                "project-name",
                error_data.get("detail", "Unable to create project.")
            )

    except Exception as e:

        print("Error connecting to backend:", e)

        show_error(
            "project-name",
            "Unable to connect to the server."
        )


@when("click", "#cancel-project")
def cancel_project(event):
    """Returns the user to the dashboard without creating a project."""

    window.location.href = "dashboard.html"