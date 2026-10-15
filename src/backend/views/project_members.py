import sys
import os
import asyncio
import html
import js # type: ignore

from pyscript import web, window, when # type: ignore

from server_data import ServerData
from project_layout import get_project_id_from_url # type: ignore


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

        profile_photo = user.get(
            "profile_photo",
            "../assets/default-profile.svg"
        )
        role = get_role_for_member(user_id, roles)

        member_data.append({
            "user_id": user_id,
            "username": username,
            "role": role,
            "profile_photo": profile_photo
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
        # Escape user-controlled values before they are placed into innerHTML.
        username = html.escape(member["username"])
        role = html.escape(member["role"])
        profile_photo = html.escape(member["profile_photo"], quote=True)

    
        cards_html += f"""
            <div class="member-card">
                <img
                    class="member-avatar"
                    src="{profile_photo}"
                    alt="Profile photo of {username}"
                >

                <div class="member-info">
                    <h2>{username}</h2>
                    <span class="role-badge">{role}</span>
                </div>
            </div>
        """

    container.innerHTML = cards_html

@when("click", "#add-member-btn")
def show_add_member_form(event):
    form = web.page["#add-member-form"]

    if form:
        form.classes.remove("hidden")


@when("click", "#cancel-add-member")
def hide_add_member_form(event):
    form = web.page["#add-member-form"]

    if form:
        form.classes.add("hidden")


@when("click", "#confirm-add-member")
async def add_member(event):
    project_id = get_project_id_from_url()

    username_input = web.page["#member-username"]
    error_element = web.page["#add-member-error"]

    if not project_id or not username_input:
        return

    username = username_input.value.strip()

    if not username:
        if error_element:
            error_element.textContent = "Please enter a username."
        return

    db = ServerData()

    success, message = await db.add_project_member(
        project_id,
        username
    )

    if not success:
        if error_element:
            error_element.textContent = message
        return

    username_input.value = ""

    form = web.page["#add-member-form"]

    if form:
        form.classes.add("hidden")

    # Reload the Members page so the new member appears.
    window.location.reload()

def populate_member_dropdown(users, existing_member_ids):
    dropdown = web.page["#member-username"]

    if not dropdown:
        return

    options_html = '<option value="">Select a member</option>'

    for user in users:
        username = html.escape(user.get("username", ""), quote=True)
        user_id = user.get("user_id")

        if user_id in existing_member_ids:
            continue

        options_html += f'''
            <option value="{username}" data-user-id="{user_id}">
                {username}
            </option>
        '''

    dropdown.innerHTML = options_html

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
    populate_member_dropdown(users, project_members.get("members", [])
)
    render_members(users, contribute_ids, roles)


asyncio.ensure_future(init_members_page())