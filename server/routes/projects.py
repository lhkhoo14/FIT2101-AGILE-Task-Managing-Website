import time
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from database_manager import db_manager
from dependencies import (
    get_verified_project, 
    verify_project_access, 
    verify_project_permission, 
    validate_role_assignment
)

router = APIRouter()

PRESET_ROLES = {
    "Project Creator": {
        "colour": "#44E",
        "description": "Highest ranking role with full project permissions.",
        "permissions": [
            "edit_project", "delete_project", "manage_members", 
            "manage_roles", "assign_roles", "manage_sprints", 
            "edit_sprints", "manage_tasks", "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Scrum Master": {
        "colour": "#E44",
        "description": "Manages sprints, team membership, tasks, and reviews.",
        "permissions": [
            "edit_project", "manage_members", "manage_roles", 
            "assign_roles", "manage_sprints", "edit_sprints", 
            "manage_tasks", "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Product Owner": {
        "colour": "#4E4",
        "description": "Manages product backlog, sprints, and team collaboration.",
        "permissions": [
            "edit_project", "manage_members", "manage_roles", 
            "assign_roles", "manage_sprints", "edit_sprints", 
            "manage_tasks", "review_tasks"
        ],
        "conflicting_roles": []
    },
    "Manager": {
        "colour": "#E4E",
        "description": "Manages sprint cycles and tasks.",
        "permissions": ["manage_sprints", "edit_sprints", "manage_tasks", "review_tasks"],
        "conflicting_roles": []
    },
    "Employee": {
        "colour": "#4EE",
        "description": "Standard contributor handling tasks and forwarding sprint items.",
        "permissions": ["edit_sprints", "manage_tasks"],
        "conflicting_roles": []
    }
}

VALID_PROJECT_STATUSES = ("active", "completed")
DEFAULT_PROJECT_STATUS = "active"

def with_project_defaults(project: dict) -> dict:
    """Returns a copy of a project with `status` and `created_at` always present.

    Projects saved before US-28 have neither field. They default to Active, and
    `created_at` is None (unknown) so the frontend sorts them oldest, falling
    back to project_id order, which is monotonic with creation order.
    """
    result = dict(project)
    result.setdefault("status", DEFAULT_PROJECT_STATUS)
    result.setdefault("created_at", None)
    return result

class CreateProjectPayload(BaseModel):
    user_id: int
    name: str
    description: str

class CreateBacklogPayload(BaseModel):
    user_id: int
    title: str
    priority: str
    tags: list[str] = Field(default_factory=list)
    # Older clients send a single tag; it is folded into `tags` below.
    tag: Optional[str] = None
    description: str = ""

class UpdateProjectStatusPayload(BaseModel):
    user_id: int
    status: str

class AddMemberPayload(BaseModel):
    user_id: int
    username: str

class AssignRolePayload(BaseModel):
    user_id: int          # Acting user
    target_user_id: int   # User receiving the role
    role_name: str        # Role to add

@router.post("/projects/{project_id}/roles/assign")
def assign_role_to_member(project_id: int, payload: AssignRolePayload):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)

    # Verify acting user has permission to manage roles
    verify_project_permission(project, payload.user_id, "manage_roles")

    if payload.target_user_id not in project.get("members", []):
        raise HTTPException(status_code=404, detail="Target user is not a project member")

    # Allow assignment if the role exists in roles map or is defined in role_definitions
    roles_map = project.setdefault("roles", {})
    role_defs = project.get("role_definitions", {})
    
    if payload.role_name not in roles_map and payload.role_name not in role_defs:
        raise HTTPException(status_code=422, detail="Invalid role specified")

    # Ensure role list exists in project roles mapping
    if payload.role_name not in roles_map:
        roles_map[payload.role_name] = []

    # Validate that adding this role doesn't break restriction rules
    validate_role_assignment(project, payload.target_user_id, payload.role_name)

    # Add user to the role list if not already present (allowing multiple roles)
    role_list = roles_map[payload.role_name]
    if payload.target_user_id not in role_list:
        role_list.append(payload.target_user_id)

    db_manager.write(db)
    return {"status": "success", "message": f"Assigned role '{payload.role_name}' successfully."}

def ensure_member_fields(project: dict) -> None:
    """Standardizes project roles, ensuring everything is unified under role_definitions and roles."""
    members = project.get("members", [])
    if "contribute" not in project:
        project["contribute"] = list(members)
        
    if "roles" not in project:
        creators = [uid for uid in project.get("creator", []) if uid in members]
        project["roles"] = {
            "Project Creator": creators,
            "Scrum Master": [],
            "Product Owner": [],
            "Manager": [],
            "Employee": [uid for uid in members if uid not in creators],
        }

    definitions = project.setdefault("role_definitions", PRESET_ROLES )

    for r_name, meta in definitions.items():
        if isinstance(meta, dict):
            meta.setdefault("permissions", [])
            meta.setdefault("conflicting_roles", [])
            meta.setdefault("colour", "#4747D4")
            meta.setdefault("description", "")
        else:
            definitions[r_name] = {
                "colour": "#4747D4",
                "description": str(meta),
                "permissions": [],
                "conflicting_roles": []
            }

    # Guarantee Project Creator has manage_roles
    if "Project Creator" in definitions:
        perms = definitions["Project Creator"].setdefault("permissions", [])
        if "manage_roles" not in perms:
            perms.append("manage_roles")

@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectPayload):
    db = db_manager.read()
    user = next((u for u in db["users"] if u["user_id"] == payload.user_id), None)

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    project_id = db.get("next_project_id", 1)
    db["next_project_id"] = project_id + 1

    new_project = {
        "project_id": project_id,
        "name": payload.name,
        "description": payload.description,
        "status": DEFAULT_PROJECT_STATUS,
        "created_at": int(time.time() * 1000),  # epoch ms, same unit as sprints
        "creator": [payload.user_id],
        "members": [payload.user_id],
        "contribute": [payload.user_id],
        "roles": {
            "Project Creator": [payload.user_id],
            "Project Manager": [],
            "Project Member": []
        },
        "role_definitions": {
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
        },
        "backlog": [],
        "sprints": []
    }

    db["projects"][str(project_id)] = new_project
    user.setdefault("projects", []).append(project_id)
    db_manager.write(db)

    return {"status": "success", "project": new_project}

@router.get("/users/{user_id}/projects")
def get_user_projects(user_id: int):
    # CHANGE: single read. find_user_by_id() reads the database again for a
    # lookup the snapshot we just loaded can already answer.
    db = db_manager.read()
    if not any(u["user_id"] == user_id for u in db.get("users", [])):
        raise HTTPException(status_code=404, detail="User not found")

    all_projects = db.get("projects", {})
    return [
        with_project_defaults(p)
        for p in all_projects.values()
        if user_id in p.get("members", [])
    ]

@router.get("/projects/{project_id}")
def get_project(project_id: int, user_id: int):
    return with_project_defaults(get_verified_project(project_id, user_id))

@router.patch("/projects/{project_id}/status")
def update_project_status(project_id: int, payload: UpdateProjectStatusPayload):
    if payload.status not in VALID_PROJECT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail="Status must be one of: " + ", ".join(VALID_PROJECT_STATUSES) + ".",
        )
    get_verified_project(project_id, payload.user_id)

    db = db_manager.read()
    project = db["projects"][str(project_id)]

    # Same rule as sprints: once ended, a project cannot be reopened.
    if project.get("status") == "completed" and payload.status == "active":
        raise HTTPException(status_code=409, detail="A completed project cannot be reopened.")

    project["status"] = payload.status
    project.setdefault("created_at", None)
    db_manager.write(db)
    return {"status": "success", "project": with_project_defaults(project)}

@router.get("/projects/{project_id}/members")
def get_project_members(project_id: int, user_id: int):
    project = get_verified_project(project_id, user_id)
    ensure_member_fields(project)

    return {
        "members": project.get("members", []),
        "contribute": project.get("contribute", []),
        "roles": project.get("roles", {}),
        "role_definitions": project.get("role_definitions", {})
    }

@router.get("/projects/{project_id}/backlog")
def get_project_backlog(project_id: int, user_id: int):
    project = get_verified_project(project_id, user_id)
    return project.get("backlog", [])

@router.post("/projects/{project_id}/backlog", status_code=status.HTTP_201_CREATED)
def create_backlog_item(project_id: int, payload: CreateBacklogPayload):
    # CHANGE: single read. get_verified_project() read the database, and the read
    # below opened a second one for the same project.
    db = db_manager.read()
    project = verify_project_access(
        db.get("projects", {}).get(str(project_id)), payload.user_id
    )

    backlog_id = db.get("next_backlog_id", 1)
    db["next_backlog_id"] = backlog_id + 1

    description = sprint_logic.clean_description(payload.description)
    if len(description) > sprint_logic.MAX_DESCRIPTION_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"The description is too long (maximum {sprint_logic.MAX_DESCRIPTION_LENGTH} characters)."
        )

    item = {
        "id": backlog_id,
        "title": payload.title,
        "tags": sprint_logic.normalize_tags(payload.tags) or sprint_logic.normalize_tags(payload.tag),
        "priority": payload.priority,
        "description": description
    }
    project.setdefault("backlog", []).append(item)
    db_manager.write(db)
    return item

@router.post("/projects/{project_id}/members")
def add_project_member(project_id: int, payload: AddMemberPayload):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)
    
    # Check if the user has the 'manage_members' permission, regardless of their role name
    verify_project_permission(project, payload.user_id, "manage_members")

    member = next(
        (user for user in db.get("users", []) if user.get("username") == payload.username),
        None
    )
    if member is None:
        raise HTTPException(status_code=404, detail="User not found")

    member_id = member["user_id"]
    if member_id in project.get("members", []):
        raise HTTPException(status_code=409, detail="User is already a project member")

    project["members"].append(member_id)
    project["contribute"].append(member_id)
    project["roles"].setdefault("Project Member", []).append(member_id)

    db_manager.write(db)

    return {
        "status": "success",
        "member_id": member_id,
        "username": member["username"],
        "role": "Project Member"
    }

class CreateRolePayload(BaseModel):
    user_id: int
    name: str
    colour: str
    description: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)
    conflicting_roles: Optional[list[str]] = Field(default_factory=list)

@router.post("/projects/{project_id}/roles", status_code=status.HTTP_201_CREATED)
def create_project_role(project_id: int, payload: CreateRolePayload):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)
    verify_project_permission(project, payload.user_id, "manage_roles")

    role_name = payload.name.strip()
    if not role_name:
        raise HTTPException(status_code=422, detail="Role name cannot be empty.")

    if role_name in project.get("roles", {}):
        raise HTTPException(status_code=409, detail="A role with this name already exists.")

    project.setdefault("roles", {})[role_name] = []

    # Store unified metadata including conflicting_roles
    definitions = project.setdefault("role_definitions", {})
    definitions[role_name] = {
        "colour": payload.colour,
        "description": payload.description or "",
        "permissions": payload.permissions,
        "conflicting_roles": payload.conflicting_roles or []
    }

    db_manager.write(db)

    return {
        "status": "success",
        "role": {
            "name": role_name,
            "colour": payload.colour,
            "description": payload.description,
            "permissions": payload.permissions,
            "conflicting_roles": payload.conflicting_roles
        }
    }

class DeleteRolePayload(BaseModel):
    user_id: int

@router.delete("/projects/{project_id}/roles/{role_name}", status_code=status.HTTP_200_OK)
def delete_project_role(project_id: int, role_name: str, payload: DeleteRolePayload):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)
    verify_project_permission(project, payload.user_id, "manage_roles")

    # Prevent deletion of core default roles
    protected_roles = {"Project Creator", "Project Manager", "Project Member"}
    if role_name in protected_roles:
        raise HTTPException(status_code=400, detail="Cannot delete default system roles.")

    roles_dict = project.get("roles", {})
    if role_name not in roles_dict and role_name not in project.get("role_definitions", {}):
        raise HTTPException(status_code=404, detail="Role not found.")

    # Remove role from assignments, definitions, and conflicts
    roles_dict.pop(role_name, None)
    project.get("role_definitions", {}).pop(role_name, None)
    
    if "role_conflicts" in project:
        project["role_conflicts"].pop(role_name, None)
        for target, conflicts in project["role_conflicts"].items():
            if role_name in conflicts:
                conflicts.remove(role_name)

    db_manager.write(db)
    return {"status": "success", "message": f"Role '{role_name}' deleted successfully."}

class UpdateRolePayload(BaseModel):
    user_id: int
    colour: str
    description: Optional[str] = None
    permissions: list[str] = Field(default_factory=list)
    conflicting_roles: Optional[list[str]] = Field(default_factory=list)

@router.put("/projects/{project_id}/roles/{role_name}", status_code=status.HTTP_200_OK)
def update_project_role(project_id: int, role_name: str, payload: UpdateRolePayload):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)
    verify_project_permission(project, payload.user_id, "manage_roles")

    protected_roles = {"Project Creator", "Project Manager", "Project Member"}
    if role_name in protected_roles:
        raise HTTPException(status_code=400, detail="Cannot modify default system roles.")

    roles_dict = project.get("roles", {})
    definitions = project.get("role_definitions", {})
    if role_name not in roles_dict and role_name not in definitions:
        raise HTTPException(status_code=404, detail="Role not found.")

    # Update unified metadata including conflicting_roles inside role_definitions
    definitions[role_name] = {
        "colour": payload.colour,
        "description": payload.description or "",
        "permissions": payload.permissions,
        "conflicting_roles": payload.conflicting_roles or []
    }

    db_manager.write(db)
    return {
        "status": "success", 
        "message": f"Role '{role_name}' updated successfully.",
        "role": {
            "name": role_name,
            "colour": payload.colour,
            "description": payload.description,
            "permissions": payload.permissions,
            "conflicting_roles": payload.conflicting_roles
        }
    }

@router.get("/projects/{project_id}/roles/{role_name}/members")
def get_role_members(project_id: int, role_name: str, user_id: int):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)
    verify_project_access(project, user_id)

    roles_map = project.get("roles", {})
    if role_name not in roles_map and role_name not in project.get("role_definitions", {}):
        raise HTTPException(status_code=404, detail="Role not found.")

    member_ids = roles_map.get(role_name, [])
    
    # Map user IDs to full user info (username, email)
    users_db = db.get("users", [])
    role_members = []
    for uid in member_ids:
        u_obj = next((u for u in users_db if u["user_id"] == uid), None)
        if u_obj:
            role_members.append({
                "user_id": u_obj["user_id"],
                "username": u_obj["username"],
                "email": u_obj.get("email", "")
            })

    return {"status": "success", "role_name": role_name, "members": role_members}

class RemoveRoleMemberPayload(BaseModel):
    user_id: int        # Acting user
    target_user_id: int # User losing the role

@router.post("/projects/{project_id}/roles/{role_name}/remove")
def remove_role_from_member(project_id: int, role_name: str, payload: RemoveRoleMemberPayload):
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    ensure_member_fields(project)
    verify_project_permission(project, payload.user_id, "manage_roles")

    # Prevent removing the last Creator if applicable
    if role_name == "Project Creator":
        creators = project.get("roles", {}).get("Project Creator", [])
        if len(creators) <= 1 and payload.target_user_id in creators:
            raise HTTPException(status_code=400, detail="Cannot remove the sole Project Creator.")

    roles_map = project.get("roles", {})
    if role_name in roles_map and payload.target_user_id in roles_map[role_name]:
        roles_map[role_name].remove(payload.target_user_id)

    db_manager.write(db)
    return {"status": "success", "message": f"Successfully removed role '{role_name}' from member."}