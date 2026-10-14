import sys
import asyncio
import html
import json
import js  # type: ignore
from pyscript import web, window, when  # type: ignore
from urllib.parse import parse_qs, urlparse, unquote

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData
from auth import show_snackbar  # type: ignore
from project_helpers import get_project_id_from_url # type: ignore
from project_role_helpers import close_all_modals, ROLE_PERMISSIONS # type: ignore

_current_role_meta = {}
_all_project_roles = []
_current_role_members = []
_role_to_delete = None

def get_role_name_from_url():
    parsed_url = urlparse(str(window.location.href))
    query_params = parse_qs(parsed_url.query)
    role_name = query_params.get("role_name", [None])[0]
    return unquote(role_name) if role_name else None

async def init_role_detail():
    global _current_role_meta, _all_project_roles
    project_id = get_project_id_from_url()
    role_name = get_role_name_from_url()
    if not project_id or not role_name:
        window.location.href = "dashboard.html"
        return

    db = ServerData()
    project_data = await db.get_project_members(project_id)
    if not project_data:
        return

    role_defs = project_data.get("role_definitions", {})
    if not role_defs:
        role_defs = {
            "Project Creator": {"colour": "#4747D4", "description": "Full administrative access to the project."},
            "Project Manager": {"colour": "#f59e0b", "description": "Manages sprints, tasks, and team coordination."},
            "Project Member": {"colour": "#10b981", "description": "Standard contributing member access."}
        }

    _all_project_roles = []
    for r_name, meta in role_defs.items():
        if isinstance(meta, dict):
            _all_project_roles.append({
                "name": r_name,
                "colour": meta.get("colour", "#4747D4"),
                "description": meta.get("description", "No description provided."),
                "permissions": meta.get("permissions", []),
                "conflicting_roles": meta.get("conflicting_roles", [])
            })

    _current_role_meta = next((r for r in _all_project_roles if r["name"] == role_name), None)
    if not _current_role_meta:
        window.location.href = f"project-roles.html?project_id={project_id}"
        return

    # Render header & description
    header_el = web.page["#role-detail-header"]
    if header_el:
        colour = _current_role_meta.get("colour", "#4747D4")
        header_el.innerHTML = f"""
        <div style="display: flex; align-items: center; gap: 12px;">
            <span class="role-swatch" style="background: {colour}; width: 24px; height: 24px; border-radius: 50%;"></span>
            <h1 class="page-title" style="margin: 0;">{html.escape(role_name)}</h1>
        </div>
        """

    desc_el = web.page["#role-detail-desc"]
    if desc_el:
        desc_el.innerText = _current_role_meta.get("description", "No description provided.")

    render_role_permissions_view(_current_role_meta.get("permissions", []))
    render_role_conflicts_view(_current_role_meta.get("conflicting_roles", []))

    protected_roles = {"Project Creator", "Project Manager", "Project Member"}
    actions_el = web.page["#role-action-buttons-container"]
    if actions_el and role_name not in protected_roles:
        actions_el.innerHTML = f"""
        <button type="button" class="create-role-btn" onclick="triggerEditRole('{role_name}')">Edit Role</button>
        <button type="button" class="create-role-btn" style="background-color: #dc2626;" onclick="triggerDeleteRole('{role_name}')">Delete Role</button>
        """

    await load_role_members(project_id, role_name)

def render_role_permissions_view(assigned_perms):
    container = js.document.getElementById("role-permissions-display")
    if not container:
        return
    if not assigned_perms:
        container.innerHTML = '<p style="color: #64748b; font-size: 13px;">No specific permissions assigned.</p>'
        return
    html_content = ""
    for p in assigned_perms:
        desc = ROLE_PERMISSIONS.get(p, p.replace('_', ' ').title())
        html_content += f'<div style="padding: 6px 10px; background: #f8fafc; border-radius: 4px; margin-bottom: 6px; font-size: 13px; color: #334155;"><strong>{p.replace("_", " ").title()}</strong>: {desc}</div>'
    container.innerHTML = html_content

def render_role_conflicts_view(conflicts):
    container = js.document.getElementById("role-conflicts-display")
    if not container:
        return
    if not conflicts:
        container.innerHTML = '<p style="color: #64748b; font-size: 13px;">No conflicting roles configured.</p>'
        return
    html_content = ""
    for c in conflicts:
        html_content += f'<span class="user-role-badge" style="margin-right: 6px; display: inline-block;">{html.escape(c)}</span>'
    container.innerHTML = html_content

async def load_role_members(project_id, role_name):
    global _current_role_members
    db = ServerData()
    _current_role_members = await db.get_role_members(project_id, role_name)
    render_role_members_list(_current_role_members)

def render_role_members_list(members):
    container = js.document.getElementById("role-members-list")
    if not container:
        return

    if not members:
        container.innerHTML = '<p style="color: #64748b; font-size: 13px;">No members assigned to this role.</p>'
        return

    html_content = ""
    for m in members:
        uid = m["user_id"]
        uname = html.escape(m["username"])
        email = html.escape(m.get("email", ""))
        html_content += f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-bottom: 1px solid #f1f5f9;">
            <div>
                <strong style="display: block; font-size: 13px; color: #1e293b;">{uname}</strong>
                <span style="font-size: 11px; color: #64748b;">{email}</span>
            </div>
            <button type="button" onclick="triggerRemoveRoleMember({uid}, '{uname}')" style="background: #fee2e2; color: #dc2626; border: none; padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer;">Remove</button>
        </div>
        """
    container.innerHTML = html_content

@when("input", "#role-members-search")
def handle_member_search(event):
    query = event.target.value.strip().casefold()
    if not query:
        render_role_members_list(_current_role_members)
        return
    filtered = [m for m in _current_role_members if query in m["username"].casefold()]
    render_role_members_list(filtered)

def trigger_edit_role_flow(role_name):
    if not _current_role_meta:
        return
    js.document.getElementById("edit-role-original-name").value = role_name
    js.document.getElementById("edit-role-name-display").value = role_name
    js.document.getElementById("edit-role-colour-input").value = _current_role_meta.get("colour", "#4F46E5")
    js.document.getElementById("edit-role-desc-input").value = _current_role_meta.get("description", "")

    populate_edit_permissions_checklist(_current_role_meta.get("permissions", []))
    populate_edit_conflict_checkboxes(_all_project_roles, role_name, _current_role_meta.get("conflicting_roles", []))

    modal = web.page["#edit-role-modal"]
    if modal:
        modal.classes.remove("hidden")

window.triggerEditRole = lambda r_name: trigger_edit_role_flow(r_name)

def populate_edit_permissions_checklist(current_perms):
    container = js.document.getElementById("edit-role-permissions-list")
    if not container:
        return
    html_content = ""
    for perm_key, perm_desc in ROLE_PERMISSIONS.items():
        is_checked = "checked" if perm_key in current_perms else ""
        html_content += f"""
        <label style="display: flex; align-items: flex-start; gap: 8px; margin-bottom: 8px; cursor: pointer;">
            <input type="checkbox" class="edit-role-permission-checkbox" value="{perm_key}" {is_checked} style="margin-top: 3px;">
            <div>
                <strong style="display: block; font-size: 12px; color: #1e293b;">{perm_key.replace('_', ' ').title()}</strong>
                <span style="font-size: 11px; color: #64748b;">{perm_desc}</span>
            </div>
        </label>
        """
    container.innerHTML = html_content

def populate_edit_conflict_checkboxes(roles, current_name, current_conflicts):
    container = js.document.getElementById("edit-role-conflicts-list")
    if not container:
        return
    html_content = ""
    for r in roles:
        r_name = r["name"]
        if r_name == current_name:
            continue
        is_checked = "checked" if r_name in current_conflicts else ""
        html_content += f'<label class="conflict-checkbox-label"><input type="checkbox" class="edit-role-conflict-checkbox" value="{html.escape(r_name)}" {is_checked}> {html.escape(r_name)}</label>'
    container.innerHTML = html_content

@when("submit", "#edit-role-form")
async def handle_edit_role_submit(event):
    if event:
        event.preventDefault()
    project_id = get_project_id_from_url()
    role_name = js.document.getElementById("edit-role-original-name").value
    colour = js.document.getElementById("edit-role-colour-input").value
    description = js.document.getElementById("edit-role-desc-input").value.strip()

    perms = [b.value for b in js.document.querySelectorAll(".edit-role-permission-checkbox:checked")]
    conflicts = [b.value for b in js.document.querySelectorAll(".edit-role-conflict-checkbox:checked")]

    modal = web.page["#edit-role-modal"]
    if modal:
        modal.classes.add("hidden")

    db = ServerData()
    success, message = await db.update_project_role(project_id, role_name, colour, description, perms, conflicts)
    if success:
        await show_snackbar(f"Role '{role_name}' updated successfully.")
        window.location.reload()
    else:
        await show_snackbar(message)

def trigger_delete_role_flow(role_name):
    global _role_to_delete
    _role_to_delete = role_name
    text_el = web.page["#delete-role-confirmation-text"]
    if text_el:
        text_el.innerHTML = f"Are you sure you want to delete the role <b>{html.escape(role_name)}</b>? This action cannot be undone."
    modal = web.page["#delete-role-modal"]
    if modal:
        modal.classes.remove("hidden")

window.triggerDeleteRole = lambda r_name: trigger_delete_role_flow(r_name)

@when("click", "#confirm-delete-role-btn")
async def confirm_delete_role(event):
    global _role_to_delete
    if not _role_to_delete:
        return
    project_id = get_project_id_from_url()
    modal = web.page["#delete-role-modal"]
    if modal:
        modal.classes.add("hidden")

    db = ServerData()
    success, message = await db.delete_project_role(project_id, _role_to_delete)
    if success:
        await show_snackbar(f"Role '{_role_to_delete}' deleted successfully.")
        window.location.href = f"project-roles.html?project_id={project_id}"
    else:
        await show_snackbar(message)
    _role_to_delete = None

_member_to_remove_id = None

def trigger_remove_role_member(uid, uname):
    global _member_to_remove_id
    _member_to_remove_id = uid
    text_el = web.page["#remove-member-confirmation-text"]
    if text_el:
        text_el.innerHTML = f"Are you sure you want to remove <b>{html.escape(uname)}</b> from this role?"
    modal = web.page["#confirm-remove-role-member-modal"]
    if modal:
        modal.classes.remove("hidden")

window.triggerRemoveRoleMember = lambda uid, uname: trigger_remove_role_member(uid, uname)

@when("click", "#confirm-remove-role-member-btn")
async def confirm_remove_role_member(event):
    global _member_to_remove_id
    if not _member_to_remove_id:
        return
    project_id = get_project_id_from_url()
    role_name = get_role_name_from_url()
    modal = web.page["#confirm-remove-role-member-modal"]
    if modal:
        modal.classes.add("hidden")
    
    if not role_name:
        return
    db = ServerData()
    success, message = await db.remove_role_member(project_id, role_name, _member_to_remove_id)
    if success:
        await show_snackbar("Member removed from role successfully.")
        window.location.reload()
    else:
        await show_snackbar(message)
    _member_to_remove_id = None

@when("click", "#open-add-member-modal-btn")
async def open_add_member_modal(event):
    project_id = get_project_id_from_url()
    role_name = get_role_name_from_url()
    db = ServerData()
    project_data = await db.get_project_members(project_id)
    if not project_data:
        return

    users_db = await db.get_all_users()
    current_ids = [m["user_id"] for m in _current_role_members]
    member_ids = project_data.get("members", [])
    
    container = js.document.getElementById("available-non-role-members-list")
    if not container:
        return

    html_content = ""
    for uid in member_ids:
        if uid in current_ids:
            continue
        u_obj = next((u for u in users_db if u.get("user_id") == uid), {"username": f"User {uid}", "email": ""})
        uname = html.escape(u_obj.get("username", ""))
        html_content += f"""
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; border-bottom: 1px solid #f1f5f9;">
            <span>{uname}</span>
            <button type="button" onclick="assignRoleToMember({uid}, '{uname}', '{role_name}')" style="background: #e0e7ff; color: #4338ca; border: none; padding: 4px 10px; border-radius: 4px; font-size: 12px; cursor: pointer;">Add</button>
        </div>
        """
    container.innerHTML = html_content or '<p style="text-align: center; color: #64748b; font-size: 13px;">No available members to add.</p>'
    
    modal = web.page["#add-role-member-modal"]
    if modal:
        modal.classes.remove("hidden")

async def assign_role_to_member_flow(user_id, username, role_name):
    project_id = get_project_id_from_url()
    db = ServerData()
    success, message = await db.assign_project_role(project_id, role_name, user_id)
    if success:
        await show_snackbar(f"Member '{username}' added to role successfully.")
        window.location.reload()
    else:
        await show_snackbar(message)

window.assignRoleToMember = lambda uid, uname, rname: asyncio.ensure_future(assign_role_to_member_flow(uid, uname, rname))

@when("click", ".modal-btn-cancel")
def close_modals(event):
    close_all_modals(["#edit-role-modal", "#delete-role-modal", "#add-role-member-modal", "#confirm-remove-role-member-modal"])

asyncio.ensure_future(init_role_detail())