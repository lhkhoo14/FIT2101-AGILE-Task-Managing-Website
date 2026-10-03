import sys
import asyncio
from pyscript import when, web, window, document  # type: ignore
from pyodide.ffi import create_proxy  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData


@when("click", "#create-project-btn")
def handle_create_project_click(event):
    window.location.replace("create-project.html")

def handle_project_click(event):
    """Navigates to project-page.html using the selected project ID."""
    card = event.currentTarget
    project_id = card.getAttribute("data-project-id")
    if project_id:
        window.location.href = f"project-page.html?project_id={project_id}"

# Create a persistent proxy wrapper for the callback
click_proxy = create_proxy(handle_project_click)

def create_project_card(project) -> web.Element:
    """Creates a project card DOM element and binds click handling."""
    card = document.createElement("div")
    card.className = "project-card"
    card.setAttribute("data-project-id", str(project.id))

    status_class = f"status-{project.status.lower()}"
    status_label = project.status.capitalize()

    card.innerHTML = f"""
        <h3 class="card-title">{project.name}</h3>
        <p class="card-details">{project.description}</p>
        <div class="card-footer">
            <span class="status-badge {status_class}">{status_label}</span>
        </div>
    """
    
    # Pass the persistent proxy to addEventListener
    card.addEventListener("click", click_proxy)
    return card

async def list_projects():
    """Fetches projects for the active user and renders them to the dashboard grid."""
    db = ServerData()
    projects = await db.get_projects()

    grid = web.page["projects-grid"]
    if not grid:
        return

    grid.innerHTML = ""  # Replace the loading state with API results.

    if not projects:
        grid.innerHTML = "<p class='no-projects'>No projects found. Click 'Create' to get started!</p>"
        return

    for project in projects:
        grid.appendChild(create_project_card(project))

# Execute project listing on page load
asyncio.ensure_future(list_projects())