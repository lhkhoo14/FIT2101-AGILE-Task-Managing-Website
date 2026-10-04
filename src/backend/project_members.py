import sys
import asyncio
import js

from pyscript import web, window

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData


def get_project_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    project_id = params.get("project_id")

    if project_id and project_id.isdigit():
        return int(project_id)

    return None


def get_role_for_member(member_id, roles):
    """Finds the assigned role for a member."""
    for role_name, member_ids in roles.items():
        if member_id in member_ids:
            return role_name

    return "Member"


def get_role_priority(role):
    """Members with assigned roles appear first."""
    if role in ["Product Owner", "Scrum Master"]:
        return 0

    if role == "Member":
        return 1

    return 2


def render_members(members, contribute_ids, roles):
    container = web.page["#member-cards"]

    if not container:
        return

    contributing_members = [
        user for user in members
        if user.get("user_id") in contribute_ids
    ]

    member_data = []

    for user in contributing_members:
        user_id = user.get("user_id")
        username = user.get("username", "Unknown User")

        role = get_role_for_member(user_id, roles)

        member_data.append({
            "user_id": user_id,
            "username": username,
            "role": role
        })

    member_data.sort(
        key=lambda member: (
            get_role_priority(member["role"]),
            member["username"].lower()
        )
    )

    if not member_data:
        container.innerHTML = """
            <p class="empty-members">
                No contributing members found.
            </p>
        """
        return

    cards_html = ""

    for member in member_data:
        username = member["username"]
        role = member["role"]

        # Use the first letter as a simple avatar until profile photos
        # are supported by the user data model.
        initial = username[0].upper() if username else "?"

        cards_html += f"""
            <div class="member-card">
                <div class="member-avatar">
                    {initial}
                </div>

                <div class="member-info">
                    <h2>{username}</h2>
                    <span class="role-badge">{role}</span>
                </div>
            </div>
        """

    container.innerHTML = cards_html


async def init_members_page():
    project_id = get_project_id_from_url()

    if not project_id:
        window.location.href = "dashboard.html"
        return

    db = ServerData()

    project_members = await db.get_project_members(project_id)

    if not project_members:
        container = web.page["#member-cards"]

        if container:
            container.innerHTML = """
                <p class="empty-members">
                    Unable to load project members.
                </p>
            """

        return

    contribute_ids = project_members.get("contribute", [])
    roles = project_members.get("roles", {})

    users = await db.get_users()

    render_members(users, contribute_ids, roles)


asyncio.ensure_future(init_members_page())