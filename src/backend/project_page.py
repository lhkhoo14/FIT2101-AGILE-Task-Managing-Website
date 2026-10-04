import sys
import asyncio
import js  # type: ignore
from html import escape
from pyscript import window, web, document  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData, Project


def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    project_id = params.get("project_id")
    if project_id and project_id.isdigit():
        return int(project_id)
    return None


def load_default_view(project: Project):
    content_el = web.page["#project-view-content"]
    description = project.description or "There is no description for this project."

    if content_el:
        content_el.innerHTML = f"""
            <div class="content-header">
                <h1 class="page-title">{project.name}</h1>
            </div>
            <div class="project-details-card" style="background:#fff; padding:24px; border-radius:8px; border:1px solid #e0e0e0;">
                <h2 style="margin-bottom:12px; font-size:18px;">Project Description</h2>
                <p style="color:#555; line-height:1.6;">{description}</p>
            </div>
        """


def _initials(name: str) -> str:
    parts = name.replace("@", " ").replace(".", " ").split()
    return "".join(part[0] for part in parts[:2]).upper() or "?"


async def load_members_view(project_id):
    team = await ServerData().get_project_team(project_id)
    content_el = web.page["#project-view-content"]
    if not content_el:
        return

    header = (
        '<div class="content-header"><h1 class="page-title">Project Members</h1>'
        f'<span class="member-count">{len(team)} member{"s" if len(team) != 1 else ""}</span></div>'
    )
    if not team:
        content_el.innerHTML = f"{header}<p class='no-projects'>No project members found.</p>"
        return

    def row_html(member):
        name = member.get("username") or member.get("email") or "Unknown user"
        email = member.get("email", "")
        return (
            "<li class='member-row'><div class='member-row-content'>"
            f"<span class='member-avatar' aria-hidden='true'>{escape(_initials(name))}</span>"
            f"<span class='member-details'><strong>{escape(name)}</strong>"
            f"<span>{escape(email)}</span></span></div></li>"
        )

    rows = "".join(row_html(member) for member in team)
    content_el.innerHTML = f"{header}<ul class='member-list'>{rows}</ul>"


async def init_project_page():
    project_id = get_project_id_from_url()

    if not project_id:
        window.location.href = "dashboard.html"
        return

    db = ServerData()
    # Fixed: Added 'await' to resolve the coroutine
    project = await db.get_project_by_id(project_id)

    view = js.URLSearchParams.new(window.location.search).get("view")
    if project and view == "members":
        await load_members_view(project_id)
    elif project:
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