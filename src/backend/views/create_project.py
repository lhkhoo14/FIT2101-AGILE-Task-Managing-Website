import asyncio
import html

from pyscript import when, web, window, document  # type: ignore
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

    for field_id in ["project-name", "project-description", "project-members"]:
        error = web.page[f"#{field_id}-error"]

        if error is not None:
            error.innerText = ""
            error.classList.remove("show")

def render_member_options(users, current_user_id):
    """Lists every registered user as a tickable member.

    The person creating the project is left out because the server already adds
    them as the owner.
    """

    container = web.page["#project-members"]

    if container is None:
        return

    options = [user for user in users if user.get("user_id") != current_user_id]

    if not options:
        container.innerHTML = (
            '<p class="members-empty">No other users have registered yet.</p>'
        )
        return

    container.innerHTML = "".join(
        '<label class="member-checkbox">'
        '<input type="checkbox" class="member-checkbox-input" value="{username}">'
        '<span class="member-name">{username}</span>'
        "</label>".format(
            username=html.escape(str(user.get("username", "")), quote=True)
        )
        for user in options
    )

def collect_selected_members():
    """Returns the usernames ticked in the Add Members list.

    CHANGE: bug fix. This used web.page["#project-members .member-checkbox-input"],
    which is document.querySelector and so returns only the FIRST checkbox in the
    list. The handler therefore read a single box no matter what was ticked, so
    every member you selected after the first was silently dropped and nobody
    showed up on the project's Members tab. querySelectorAll reads all of them,
    which is how the sprint dashboard already collects its member checkboxes.
    """

    boxes = document.querySelectorAll("#project-members .member-checkbox-input")

    return [box.value for box in boxes if box.checked]

async def load_members():
    """Fills the Add Members list with every registered user."""

    db = ServerData()
    users = await db.get_users()
    render_member_options(users, db.get_active_session())

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
        # CHANGE: new. The create-project API only takes a name and description,
        # so members cannot be attached up front. The project exists at this
        # point, so each ticked username from the Add Members list is added now.
        # The add endpoint appends to members, contribute and roles, which is
        # what project-members.html reads, so these show on the Members tab.
        added = 0
        rejected = []

        for username in collect_selected_members():
            ok, message = await db.add_project_member(project_id, username)
            if ok:
                added += 1
            else:
                # CHANGE: the (ok, message) return used to be thrown away, so a
                # failed add looked like a success. It is logged and reported now.
                rejected.append(username)
                print(f"[Members] Could not add '{username}': {message}")

        if rejected:
            await show_snackbar(
                "Project created, but "
                f"{len(rejected)} member(s) could not be added."
            )
        else:
            await show_snackbar(
                "Project created successfully!"
                + (f" {added} member(s) added." if added else "")
            )

        window.location.replace(f"project-page.html?project_id={project_id}")
    else:
        show_error("project-name", error_message)
        await show_snackbar(error_message)


@when("click", "#cancel-project")
def cancel_project(event):
    """Returns the user to the dashboard without creating a project."""

    window.location.href = "dashboard.html"


asyncio.ensure_future(load_members())