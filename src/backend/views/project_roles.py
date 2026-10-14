import sys
import asyncio
import html
import js  # type: ignore
from pyscript import document, web, window, when  # type: ignore
from urllib.parse import quote

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData
from project_layout import get_project_id_from_url  # type: ignore
from auth import show_snackbar  # type: ignore

from project_role_helpers import ROLE_PERMISSIONS # type: ignore

# Manager can edit project, add members, 
# Employees can create tasks, drag sprint tasks, 

# Store active roles globally in module state for search filtering
_all_roles = []

async def load_project_roles():
    global _all_roles
    project_id = get_project_id_from_url()
    if not project_id:
        window.location.href = "dashboard.html"
        return

    db = ServerData()
    project_data = await db.get_project_members(project_id)
    if not project_data:
        container = web.page["#roles-cards-container"]
        if container:
            container.innerHTML = '<p class="empty-roles">Unable to load project roles.</p>'
        return

    current_user_id = db.get_active_session()
    roles_map = project_data.get("roles", {})
    role_defs = project_data.get("role_definitions", {})

    user_roles = []
    for r_name, member_ids in roles_map.items():
        if current_user_id in member_ids or str(current_user_id) in [str(m) for m in member_ids]:
            user_roles.append(r_name)

    render_user_roles_banner(user_roles, role_defs)

    if not role_defs:
        role_defs = {
            "Project Creator": {"colour": "#4747D4", "description": "Full administrative access to the project."},
            "Project Manager": {"colour": "#f59e0b", "description": "Manages sprints, tasks, and team coordination."},
            "Project Member": {"colour": "#10b981", "description": "Standard contributing member access."}
        }

    _all_roles = []
    for role_name, meta in role_defs.items():
        if isinstance(meta, dict):
            _all_roles.append({
                "name": role_name,
                "colour": meta.get("colour", "#4747D4"),
                "description": meta.get("description", "No description provided."),
                "permissions": meta.get("permissions", []),
                "conflicting_roles": meta.get("conflicting_roles", [])
            })
        else:
            _all_roles.append({
                "name": role_name,
                "colour": "#4747D4",
                "description": str(meta),
                "permissions": [],
                "conflicting_roles": []
            })

    render_roles_view(_all_roles)
    populate_permission_checkboxes() # Populate dynamic permissions list
    populate_conflict_checkboxes(_all_roles)

def populate_permission_checkboxes():
    container = js.document.getElementById("role-permissions-list")
    if not container:
        return
    
    html_content = ""
    for perm_key, perm_desc in ROLE_PERMISSIONS.items():
        safe_key = html.escape(perm_key, quote=True)
        safe_desc = html.escape(perm_desc)
        title_text = html.escape(perm_key.replace('_', ' ').title())
        
        html_content += f"""
        <label class="permission-item-label" style="display: flex; align-items: flex-start; gap: 8px; margin-bottom: 10px; cursor: pointer;">
            <input type="checkbox" class="role-permission-checkbox" value="{safe_key}" style="margin-top: 3px;">
            <div>
                <strong style="display: block; font-size: 13px; color: #1e293b;">{title_text}</strong>
                <span style="font-size: 12px; color: #64748b;">{safe_desc}</span>
            </div>
        </label>
        """
    container.innerHTML = html_content

def populate_conflict_checkboxes(roles):
    conflict_container = js.document.getElementById("role-conflicts-list")
    if not conflict_container:
        return
    
    boxes_html = ""
    for role in roles:
        r_name = html.escape(role["name"])
        boxes_html += f'<label class="conflict-checkbox-label"><input type="checkbox" class="role-conflict-checkbox" value="{r_name}"> {r_name}</label>'
    conflict_container.innerHTML = boxes_html

def render_user_roles_banner(user_roles, role_defs):
    banner_container = web.page["#user-active-roles-banner"]
    if not banner_container:
        return

    if not user_roles:
        banner_container.innerHTML = '<div class="user-roles-banner"><span>Your Active Roles: </span><span class="no-role-badge">None assigned</span></div>'
        return

    badges_html = ""
    for r_name in user_roles:
        meta = role_defs.get(r_name, {})
        colour = meta.get("colour", "#4747D4") if isinstance(meta, dict) else "#4747D4"
        badges_html += f'<span class="user-role-badge" style="border-left: 4px solid {colour};">{html.escape(r_name)}</span>'

    banner_container.innerHTML = f"""
    <div class="user-roles-banner">
        <span class="banner-label">Your Active Roles in this Project:</span>
        <div class="banner-badges-container">{badges_html}</div>
    </div>
    """

def render_roles_view(roles_to_render):
    container = web.page["#roles-cards-container"]
    if not container:
        return

    # Get the project_id once here in Python where the helper is available
    project_id = get_project_id_from_url() or ""

    html_content = ""
    if not roles_to_render:
        html_content = '<p class="empty-roles">No roles found matching your search.</p>'
    else:
        for role in roles_to_render:
            name = html.escape(role["name"])
            colour = html.escape(role["colour"], quote=True)
            description = html.escape(role["description"])
            safe_role_name = quote(role["name"])
            
            html_content += f"""
            <div class="role-card" style="cursor: pointer;" onclick="window.location.href='project-role-details.html?project_id={project_id}&role_name={safe_role_name}'">
                <div class="role-card-header">
                    <div class="role-title-group">
                        <span class="role-swatch" style="background: {colour};"></span>
                        <h3 class="role-name">{name}</h3>
                    </div>
                    <span class="toggle-icon">→</span>
                </div>
                <div class="role-description-container">
                    <p class="role-description">{description}</p>
                </div>
            </div>
            """
    container.innerHTML = html_content

# --- UI Event Handlers ---

@when("input", "#role-search-input")
def handle_role_search(event):
    query = event.target.value.strip().casefold()
    if not query:
        render_roles_view(_all_roles)
        return

    # Search filtering: check names first, then descriptions
    name_matches = []
    desc_matches = []

    for role in _all_roles:
        if query in role["name"].casefold():
            name_matches.append(role)
        elif query in role["description"].casefold():
            desc_matches.append(role)

    filtered = name_matches + desc_matches
    render_roles_view(filtered)

# Global JS helper for toggling role description accordion
window.toggleRoleDescription = lambda header_el: (
    header_el.nextElementSibling.classList.toggle("hidden")
) if hasattr(header_el, "nextElementSibling") and header_el.nextElementSibling else None

@when("click", "#open-create-role-modal")
def open_role_modal(event):
    modal = web.page["#create-role-modal"]
    if modal:
        modal.classList.remove("hidden")

@when("click", ".modal-btn-cancel")
def close_role_modal(event):
    # Use standard class matching or target checking safely
    for modal_sel in ["#create-role-modal", "#edit-role-modal", "#manage-role-members-modal", "#add-role-member-modal"]:
        m = web.page[modal_sel]
        if m and "hidden" not in m.classes:
            m.classes.add("hidden")

@when("submit", "#create-role-form")
async def handle_create_role(event):
    if event:
        event.preventDefault()

    project_id = get_project_id_from_url()
    if not project_id:
        return

    name_el = web.page["#role-name-input"]
    colour_el = web.page["#role-colour-input"]
    desc_el = web.page["#role-desc-input"]

    name = name_el.value.strip() if name_el else ""
    colour = colour_el.value if colour_el else "#4F46E5"
    description = desc_el.value.strip() if desc_el else ""

    if not name:
        # Hide modal first if validation fails
        modal = web.page["#create-role-modal"]
        if modal:
            modal.classList.add("hidden")
        await show_snackbar("Role name is required.")
        return

    permission_boxes = js.document.querySelectorAll(".role-permission-checkbox:checked")
    permissions = [box.value for box in permission_boxes]

    conflict_boxes = js.document.querySelectorAll(".role-conflict-checkbox:checked")
    conflicting_roles = [box.value for box in conflict_boxes]

    # Hide modal before making the API call / showing snackbar
    modal = web.page["#create-role-modal"]
    if modal:
        modal.classList.add("hidden")

    db = ServerData()
    success, message = await db.create_project_role(
        project_id=project_id,
        name=name,
        colour=colour,
        description=description,
        permissions=permissions,
        conflicting_roles=conflicting_roles
    )

    if success:
        await show_snackbar("Custom role created successfully!")
        window.location.reload()
    else:
        await show_snackbar(message)

# Initialize on page load
asyncio.ensure_future(load_project_roles())