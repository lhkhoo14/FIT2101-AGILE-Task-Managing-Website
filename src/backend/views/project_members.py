import asyncio
import html

from pyscript import web, window, when # type: ignore

# `auth` and `dialog` are loaded by their flat names via settings.json's file
# map (src/backend/utils/auth.py -> ./auth.py), so Pylance cannot resolve them
# from this folder; the ignores keep those runtime-correct imports quiet.
from auth import show_snackbar  # type: ignore
from dialog import confirm_action  # type: ignore
from project_role_helpers import permissions_for_user, can_remove_member, member_permission_sets # type: ignore
from server_data import ServerData
from project_layout import get_project_id_from_url # type: ignore


# CHANGE: removing a member is behind an on/off switch, so a mis-click on a card
# cannot remove a teammate. The switch is offered only to a manage_members
# holder, and its position lives in sessionStorage so a reload does not silently
# re-arm the roster. This state is what the rendering below reads.
_REMOVE_MODE_KEY = "project_members_remove_mode"

_can_manage_members = False
_remove_mode = False
_actor_id = None
_users = []
_members_payload = None


def _set_remove_mode(is_on: bool) -> None:
    """Remember whether the remove switch is on, for this browser session."""
    global _remove_mode
    _remove_mode = bool(is_on)
    try:
        window.sessionStorage.setItem(_REMOVE_MODE_KEY, "1" if _remove_mode else "0")
    except Exception as exc:
        print(f"[Members] Could not store the remove switch: {exc}")


def _stored_remove_mode() -> bool:
    """The switch position this browser session last used (off by default)."""
    try:
        return window.sessionStorage.getItem(_REMOVE_MODE_KEY) == "1"
    except Exception:
        return False


def _removable_member_ids() -> set:
    """Who may be offered a Remove control right now.

    Empty while the switch is off. With it on, a member is listed when this user
    outranks them (see can_remove_member: preset rank first, then permission
    sets, and never themselves) - the same judgement the Roles page makes about
    who sits above whom.
    """
    if not _remove_mode or _members_payload is None:
        return set()

    listed = set(member_permission_sets(_members_payload))
    listed.update(str(uid) for uid in _members_payload.get("contribute", []) or [])

    removable = set()
    for raw in listed:
        try:
            uid = int(raw)
        except (TypeError, ValueError):
            continue
        if can_remove_member(_members_payload, _actor_id, uid):
            removable.add(uid)
    return removable


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


def render_members(members, contribute_ids, roles, removable_ids=None):
    """Renders the member cards.

    a Remove control is drawn only for the ids in removable_ids, which the page
    passes only while the remove switch is on and only for the members the
    signed-in user outranks. The server re-checks manage_members on the request,
    so this decides what is offered, not what is allowed.
    """
    removable_ids = removable_ids or set()
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

        # Removing a member needs manage_members and is switched on deliberately;
        # both are checked before the control is offered at all.
        remove_html = ""
        if member["user_id"] in removable_ids:
            remove_html = (
                f'<button type="button" class="member-remove-btn"'
                f' data-member-id="{member["user_id"]}"'
                f' data-member-name="{username}"'
                f' title="Remove from this project">Remove</button>'
            )

    
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
                    {remove_html}
                </div>
            </div>
        """

    container.innerHTML = cards_html
    # The Remove buttons are handled by the @when listener on #member-cards below,
    # so the markup only has to be drawn: nothing is attached to the cards.

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

    # Refresh the roster in place so the new member appears without a reload.
    # A reload would also throw away the remove switch's position.
    await refresh_member_view()


async def refresh_member_view():
    """Re-read the roster and draw it again, keeping the switch where it is."""
    project_id = get_project_id_from_url()
    if not project_id:
        return

    db = ServerData()
    payload = await db.get_project_members(project_id)
    if not payload:
        return

    global _members_payload, _users, _actor_id, _can_manage_members
    _members_payload = payload
    _actor_id = db.get_active_session()
    permissions = permissions_for_user(payload, _actor_id)
    _can_manage_members = "manage_members" in permissions

    _users = await db.get_users()
    populate_member_dropdown(_users, payload.get("members", []))
    _apply_remove_mode_control()
    _render_member_cards()


def _apply_remove_mode_control():
    """Show the switch to manage_members holders and sync it with the state."""
    toggle = web.page["#remove-mode-toggle"]
    checkbox = web.page["#remove-mode-checkbox"]
    if toggle is None or checkbox is None:
        return

    if not _can_manage_members:
        # Not their call to make: no switch, and no Remove controls either.
        _set_remove_mode(False)
        toggle.classes.add("hidden")
        checkbox.checked = False
        return

    toggle.classes.remove("hidden")
    checkbox.checked = _remove_mode


def _render_member_cards():
    """Draw the roster with the current switch state (see render_members)."""
    if _members_payload is None:
        return
    render_members(
        _users,
        _members_payload.get("contribute", []),
        _members_payload.get("roles", {}),
        _removable_member_ids(),
    )


@when("change", "#remove-mode-checkbox")
async def handle_remove_mode_change(event):
    """The switch was flipped: redraw the roster with or without Remove controls."""
    _set_remove_mode(event.target.checked)
    _render_member_cards()
    await show_snackbar(
        "Remove controls are on for the members you outrank."
        if _remove_mode else "Remove controls are off."
    )


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

@when("click", "#member-cards")
async def handle_remove_member_click(event):
    """Take the member out of the project, once the user confirms.

    The listener sits on the roster container rather than on the button: the
    cards, and with them the Remove buttons, are drawn again after every change,
    while #member-cards is in the page's own markup - which matters because
    PyScript resolves a @when selector when the decorator runs, and raises if
    nothing matches yet.

    The clicked button is read from event.target, not event.currentTarget: an
    async handler's body runs after the click has finished dispatching, and the
    browser has cleared currentTarget by then, which is what made the old
    create_proxy wiring on the button itself do nothing at all. event.target
    keeps pointing at what was clicked (the sprint page's checklist delete
    handler relies on the same thing).
    """
    target = event.target
    button = target.closest(".member-remove-btn") if target is not None else None
    if button is None:
        return

    member_id = button.getAttribute("data-member-id")
    name = button.getAttribute("data-member-name") or "this member"
    if not member_id:
        return

    confirmed, _password = await confirm_action(title=f"Remove {name}")
    if not confirmed:
        return

    success, message = await ServerData().remove_project_member(
        get_project_id_from_url(),
        member_id
    )

    await show_snackbar(message)

    if success:
        # Draw the roster again from the server so the card and the role lists
        # match, without reloading away the remove switch.
        await refresh_member_view()

async def init_members_page():
    project_id = get_project_id_from_url()

    if not project_id:
        window.location.href = "dashboard.html"
        return

    # The switch comes back the way this session left it, so a reload cannot
    # silently turn destructive controls on (or off) behind the user's back.
    _set_remove_mode(_stored_remove_mode())

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

    global _members_payload, _actor_id, _users, _can_manage_members
    _members_payload = project_members
    _actor_id = db.get_active_session()
    # The same payload decides which destructive controls this page offers.
    permissions = permissions_for_user(project_members, _actor_id)
    _can_manage_members = "manage_members" in permissions

    _users = await db.get_users()
    populate_member_dropdown(_users, project_members.get("members", [])
)
    _apply_remove_mode_control()
    _render_member_cards()


asyncio.ensure_future(init_members_page())