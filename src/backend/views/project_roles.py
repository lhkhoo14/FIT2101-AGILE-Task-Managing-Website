import sys
import asyncio
import html
import js  # type: ignore
from pyscript import web, window, when  # type: ignore

if "." not in sys.path:
    sys.path.append(".")

from server_data import ServerData
from project_layout import get_project_id_from_url  # type: ignore
from auth import show_snackbar  # type: ignore

role_permissions = [
    "manage_roles",
    "manage_sprints",
    "view_contributions",
    "edit_project",
    "delete_project",
    "add_members",
    "remove_members"
]

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

    # Extract role definitions and assignments from project record
    role_defs = project_data.get("role_definitions", {})
    
    # Fallback default roles if none are defined yet
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
                "description": meta.get("description", "No description provided.")
            })
        else:
            _all_roles.append({
                "name": role_name,
                "colour": "#4747D4",
                "description": str(meta)
            })

    render_roles_view(_all_roles)
    populate_conflict_checkboxes(_all_roles)

def render_roles_view(roles_to_render):
    # Target only the cards container so header/search inputs are never destroyed
    container = web.page["#roles-cards-container"]
    if not container:
        return

    html_content = ""
    if not roles_to_render:
        html_content = '<p class="empty-roles">No roles found matching your search.</p>'
    else:
        for role in roles_to_render:
            name = html.escape(role["name"])
            colour = html.escape(role["colour"], quote=True)
            description = html.escape(role["description"])

            html_content += f"""
            <div class="role-card" data-role-name="{name}">
                <div class="role-card-header" onclick="toggleRoleDescription(this)">
                    <div class="role-title-group">
                        <span class="role-swatch" style="background: {colour};"></span>
                        <h3 class="role-name">{name}</h3>
                    </div>
                    <span class="toggle-icon">▼</span>
                </div>
                <div class="role-description-container hidden">
                    <p class="role-description">{description}</p>
                </div>
            </div>
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
    modal = web.page["#create-role-modal"]
    if modal:
        modal.classList.add("hidden")

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
        await show_snackbar("Role name is required.")
        return

    permission_boxes = js.document.querySelectorAll(".role-permission-checkbox:checked")
    permissions = [box.value for box in permission_boxes]

    conflict_boxes = js.document.querySelectorAll(".role-conflict-checkbox:checked")
    conflicting_roles = [box.value for box in conflict_boxes]

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