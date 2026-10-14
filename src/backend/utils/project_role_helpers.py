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
    "edit_project": "Allow members to edit project description",
    "delete_project": "Allow members to delete the project",
}

PRESET_ROLES = {
    "Creator": {
        "colour": "#44E",
        "description": "Highest ranking role with full permissions.",
        "permissions": [
            "manage_members",
            "manage_roles",
            "assign_roles",
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks",
            "edit_project",
            "delete_project"
        ],
        "conflicting_roles": []
    },
    "Scrum Master": {
        "colour": "#EE4",
        "description": "Highest ranking role with full permissions.",
        "permissions": [
            "manage_members",
            "manage_roles",
            "assign_roles",
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks",
            "edit_project",
        ],
        "conflicting_roles": []
    },
    "Product Owner": {
        "colour": "#44E",
        "description": "Highest ranking role with full permissions.",
        "permissions": [
            "manage_members",
            "manage_roles",
            "assign_roles",
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks",
            "edit_project",
            "manage_sprints"
        ],
        "conflicting_roles": []
    },
    "Manager": {
        "colour": "#44E",
        "description": "Highest ranking role with full permissions.",
        "permissions": [
            "manage_sprints",
            "edit_sprints",
            "manage_tasks",
            "review_tasks",
        ],
        "conflicting_roles": []
    },
    "Employee": {
        "colour": "#44E",
        "description": "Highest ranking role with full permissions.",
        "permissions": [
            "edit_sprints",
            "manage_tasks",
        ],
        "conflicting_roles": []
    }
}

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