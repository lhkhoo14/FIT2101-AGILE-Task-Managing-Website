import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import web, document  # type: ignore
from server_data import ServerData

def create_project_card(project) -> web.Element:
    """Creates a project card DOM element."""
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
    return card

async def list_projects():
    """Fetches projects for the active user and renders them to the dashboard grid."""
    db = ServerData()
    projects = await db.get_projects()

    grid = web.page["projects-grid"]
    if not grid:
        return

    grid.innerHTML = ""  # Clear hardcoded placeholder cards

    if not projects:
        grid.innerHTML = "<p class='no-projects'>No projects found. Click 'Create' to get started!</p>"
        return

    for project in projects:
        grid.appendChild(create_project_card(project))

# Execute project listing on page load
asyncio.ensure_future(list_projects())