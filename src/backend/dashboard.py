import sys
import asyncio
from html import escape
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

# --- Sorting (US-28) ---
SORT_DATE_DESC = "date-desc"
SORT_DATE_ASC = "date-asc"
SORT_STATUS = "status"
SORT_NAME = "name"

# Status sort order: what users most likely want to find first comes first.
STATUS_ORDER = {"active": 0, "completed": 1, "archived": 2}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Projects as last fetched from the server. Sorting re-renders from this list,
# so changing the dropdown never needs another network request or page reload.
loaded_projects: list = []


def _created_key(project) -> tuple:
    """Sort key for creation time. Legacy projects have no created_at; they
    count as oldest, and project id (which grows with creation) orders them."""
    try:
        pid = int(project.id)
    except (TypeError, ValueError):
        pid = 0
    return (project.created_at or 0, pid)


def sort_projects(projects, sort_key: str) -> list:
    """Returns a new, sorted list. Ties keep a stable, predictable order.

    date-desc -> newest first (default)
    date-asc  -> oldest first
    status    -> Active, Completed, Archived; newest first within each status
    name      -> A-Z, case-insensitive
    """
    items = list(projects)
    if sort_key == SORT_DATE_ASC:
        return sorted(items, key=_created_key)
    if sort_key == SORT_STATUS:
        newest_first = sorted(items, key=_created_key, reverse=True)
        return sorted(newest_first, key=lambda p: STATUS_ORDER.get(str(p.status).lower(), len(STATUS_ORDER)))
    if sort_key == SORT_NAME:
        return sorted(items, key=lambda p: str(p.name).casefold())
    return sorted(items, key=_created_key, reverse=True)


def filter_projects(projects, query: str) -> list:
    """Projects matching the search text. Returns all projects for an empty query.

    The query is split on whitespace and every word must partially match the
    project's name or description (case-insensitive), so "web" finds "Website
    redesign" and "web redesign" finds it too.
    """
    terms = str(query or "").casefold().split()
    if not terms:
        return list(projects)
    result = []
    for project in projects:
        haystack = f"{project.name} {project.description}".casefold()
        if all(term in haystack for term in terms):
            result.append(project)
    return result


def current_search_query() -> str:
    search = web.page["global-search"]
    return search.value.strip() if search is not None else ""


def format_created_date(created_at) -> str:
    """Formats epoch milliseconds as e.g. '13 Oct 2026' in the user's timezone."""
    if not created_at:
        return "Unknown"
    d = window.Date.new(created_at)
    return f"{d.getDate()} {MONTHS[d.getMonth()]} {d.getFullYear()}"


def current_sort_key() -> str:
    select = web.page["sort-select"]
    return select.value if select is not None else SORT_DATE_DESC


def create_project_card(project) -> web.Element:
    """Creates a project card DOM element and binds click handling."""
    card = document.createElement("div")
    card.className = "project-card"
    card.setAttribute("data-project-id", str(project.id))

    status = str(project.status).lower()
    status_class = f"status-{escape(status)}"
    status_label = status.capitalize()
    created_label = format_created_date(project.created_at)

    card.innerHTML = f"""
        <h3 class="card-title">{escape(str(project.name))}</h3>
        <p class="card-details">{escape(str(project.description))}</p>
        <div class="card-footer">
            <span class="status-badge {status_class}">{escape(status_label)}</span>
            <span class="card-date">Created {created_label}</span>
        </div>
    """
    
    # Pass the persistent proxy to addEventListener
    card.addEventListener("click", click_proxy)
    return card

def render_projects():
    """Sorts the loaded projects by the selected option and redraws the grid."""
    grid = web.page["projects-grid"]
    if not grid:
        return

    grid.innerHTML = ""  # Clear hardcoded placeholder cards

    if not loaded_projects:
        grid.innerHTML = "<p class='no-projects'>No projects found. Click 'Create' to get started!</p>"
        return

    query = current_search_query()
    visible = filter_projects(loaded_projects, query)
    if not visible:
        grid.innerHTML = f"<p class='no-projects'>No projects match \"{escape(query)}\".</p>"
        return

    for project in sort_projects(visible, current_sort_key()):
        grid.appendChild(create_project_card(project))


async def list_projects():
    """Fetches projects for the active user and renders them to the dashboard grid."""
    global loaded_projects
    db = ServerData()
    loaded_projects = await db.get_projects() or []
    render_projects()


@when("input", "#global-search")
def handle_search_input(event):
    """Filters the cards as the user types; no page reload or refetch."""
    render_projects()


@when("change", "#sort-select")
def handle_sort_change(event):
    """Reorders the cards in place; no page reload or refetch."""
    render_projects()

# Execute project listing on page load
asyncio.ensure_future(list_projects())