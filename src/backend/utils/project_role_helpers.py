from typing import Optional
import html
import js  # type: ignore
from pyscript import web, window  # type: ignore
from urllib.parse import parse_qs, urlparse, unquote

ROLE_PERMISSIONS = {
    "manage_members": "Allow members to add and remove members to the project.",
    "manage_roles": "Allow members to create custom roles, delete existing roles, and configure role permissions/conflicts.",
    "assign_roles": "Allow members to assign roles to members.",
    "manage_sprints": "Allow members to create, edit or delete sprints.",
    "edit_sprints": "Allow members to move tasks forward in sprints.", 
    "manage_tasks": "Allow members to create, edit or delete tasks",
    "review_tasks": "Allow members to move tasks from In Review to Complete and move tasks backwards.",
    "edit_project": "Allow members to edit the project's description and status.",
    "delete_project": "Allow members to delete the project",
}

PRESET_ROLES = {
    "Project Creator": {
        "colour": "#44E",
        "description": "Highest ranking role with full project permissions.",
        "permissions": [
            "edit_project",
            "delete_project",
            "manage_members",
            "manage_roles",
            "assign_roles",
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Scrum Master": {
        "colour": "#E44",
        "description": "Manages sprints, team membership, tasks, and reviews.",
        "permissions": [
            "edit_project",
            "manage_members",
            "manage_roles",
            "assign_roles",
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Product Owner": {
        "colour": "#4E4",
        "description": "Manages product backlog, sprints, and team collaboration.",
        "permissions": [
            "edit_project",
            "manage_members",
            "manage_roles",
            "assign_roles",
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Manager": {
        "colour": "#E4E",
        "description": "Manages sprint cycles and tasks.",
        "permissions": [
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Employee": {
        "colour": "#4EE",
        "description": "Standard contributor handling tasks and forwarding sprint items.",
        "permissions": [
            "edit_sprints",
            "manage_tasks",
        ],
        "conflicting_roles": []
    }
}

PROTECTED_PRESET_NAMES = set(PRESET_ROLES.keys())

def get_role_name_from_url() -> str | None:
    """Extracts and unquotes the role_name parameter from the current URL query string."""
    parsed_url = urlparse(str(window.location.href))
    query_params = parse_qs(parsed_url.query)
    role_name = query_params.get("role_name", [None])[0]
    return unquote(role_name) if role_name else None

def close_all_modals(modal_selectors: list[str]):
    """Closes a list of modal overlays by adding the 'hidden' class."""
    for sel in modal_selectors:
        m = web.page[sel]
        if m and "hidden" not in m.classes:
            m.classes.add("hidden")

def build_permissions_checklist_html(role_permissions: dict, current_permissions: Optional[list[str]]) -> str:
    """Generates reusable HTML string for role permissions checklists."""
    current_perms = current_permissions or []
    html_content = ""
    for perm_key, perm_desc in role_permissions.items():
        is_checked = "checked" if perm_key in current_perms else ""
        safe_key = html.escape(perm_key, quote=True)
        safe_desc = html.escape(perm_desc)
        title_text = html.escape(perm_key.replace('_', ' ').title())
        html_content += f"""
        <label style="display: flex; align-items: flex-start; gap: 8px; margin-bottom: 8px; cursor: pointer;">
            <input type="checkbox" class="edit-role-permission-checkbox role-permission-checkbox" value="{safe_key}" {is_checked} style="margin-top: 3px;">
            <div>
                <strong style="display: block; font-size: 12px; color: #1e293b;">{title_text}</strong>
                <span style="font-size: 11px; color: #64748b;">{safe_desc}</span>
            </div>
        </label>
        """
    return html_content

def permissions_for_user(project_payload: Optional[dict],
                         user_id: Optional[int] | str) -> set[str]:
    """The permissions a user holds in a project.

    The id may arrive as an int (the signed-in user) or as a string, which is
    how a roles map keys its holders (see member_permission_sets); it is
    normalised with str() before anything is compared.

    Accepts either a `/projects/{id}/members` payload or a raw project record,
    which carry roles and role_definitions under the same keys. Used to decide
    which destructive controls a page offers - the server enforces the same
    permissions on every request, so this only stops the UI from presenting an
    action that would come straight back as a 403.
    """
    if not project_payload or user_id is None:
        return set()

    roles = project_payload.get("roles") or {}
    definitions = project_payload.get("role_definitions") or {}
    wanted = str(user_id)

    granted: set[str] = set()
    for role_name, holders in roles.items():
        if not isinstance(holders, list):
            continue
        if wanted not in {str(holder) for holder in holders}:
            continue
        meta = definitions.get(role_name)
        permissions = meta.get("permissions") if isinstance(meta, dict) else None
        if isinstance(permissions, list):
            granted.update(permissions)
    return granted


# Preset roles by authority. Custom roles have no rank of their own, so they are
# compared by the permissions they grant instead (see can_remove_member).
PRESET_RANK = {
    "Project Creator": 5,
    "Scrum Master": 4,
    "Product Owner": 4,
    "Manager": 3,
    "Employee": 2,
}

# Preset roles only one member may hold at a time: the three leadership posts.
# The Add Member list offers nobody while one of these is filled, because the
# sitting holder always ranks at least as high as the role itself (see the rank
# filter in project_role_details.py). server/dependencies.py enforces the same
# rule, so the list and the route agree on who may be added.
SINGLETON_PRESET_ROLES = ("Project Creator", "Scrum Master", "Product Owner")

# A member holding only custom roles, or no role at all, ranks below every preset.
UNRANKED = 1


def highest_preset_rank(project_payload: Optional[dict],
                        user_id: Optional[int] | str) -> int:
    """The rank of the member's most senior preset role (UNRANKED if they hold none)."""
    roles = (project_payload or {}).get("roles") or {}
    wanted = str(user_id)
    best = UNRANKED
    for role_name, holders in roles.items():
        if not isinstance(holders, list):
            continue
        if wanted not in {str(holder) for holder in holders}:
            continue
        best = max(best, PRESET_RANK.get(role_name, UNRANKED))
    return best


def member_permission_sets(project_payload: Optional[dict]) -> dict[str, set[str]]:
    """Every member listed in the payload's role map, mapped to their permissions.

    Members with no role appear with an empty set, so the comparison in
    can_remove_member() still has an entry for them.
    """
    roles = (project_payload or {}).get("roles") or {}
    keys = {
        str(holder)
        for holders in roles.values()
        if isinstance(holders, list)
        for holder in holders
    }
    return {key: permissions_for_user(project_payload, key) for key in keys}


def can_remove_member(project_payload: Optional[dict],
                      actor_id: Optional[int] | str,
                      target_id: Optional[int] | str) -> bool:
    """Whether actor_id outranks target_id enough to remove them from the project.

    Two tests, in this order:

    1. Preset rank - Project Creator > Scrum Master = Product Owner > Manager >
       Employee, with custom roles and role-less members below all of them.
    2. Permission sets - the member holding the strictly larger set wins. This is
       the tie-breaker between two members of equal rank, which is the only way
       custom roles can be compared (they have no rank), and it also vetoes a
       removal that rank alone would allow when the target actually holds more
       power than the actor, so a custom role cannot be removed by someone it
       out-permissions.

    The actor is never removable, and neither is a peer: the worst outcome is
    "you cannot remove this person", never a way to remove someone above you.
    Server-side this is presentation only - the endpoint re-checks manage_members
    on the request - so the rules here are deliberately conservative.
    """
    if actor_id is None or target_id is None:
        return False
    if str(actor_id) == str(target_id):
        return False

    permission_sets = member_permission_sets(project_payload)
    actor_permissions = permission_sets.get(str(actor_id)) or permissions_for_user(project_payload, actor_id)
    target_permissions = permission_sets.get(str(target_id)) or set()

    actor_rank = highest_preset_rank(project_payload, actor_id)
    target_rank = highest_preset_rank(project_payload, target_id)

    if target_rank > actor_rank:
        return False
    if target_rank == actor_rank:
        return target_permissions < actor_permissions
    return not (actor_permissions < target_permissions)


def build_conflicts_checklist_html(roles: list[dict], current_role_name: Optional[str], current_conflicts: Optional[list[str]]) -> str:
    """Generates reusable HTML string for conflicting roles checklists."""
    current_conflicts = current_conflicts or []
    html_content = ""
    for role in roles:
        r_name = role.get("name", "")
        if current_role_name and r_name == current_role_name:
            continue
        is_checked = "checked" if r_name in current_conflicts else ""
        safe_name = html.escape(r_name)
        html_content += f'<label class="conflict-checkbox-label"><input type="checkbox" class="role-conflict-checkbox edit-role-conflict-checkbox" value="{safe_name}" {is_checked}> {safe_name}</label>'
    return html_content