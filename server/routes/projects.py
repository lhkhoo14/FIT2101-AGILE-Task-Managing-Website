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

class CreateProjectPayload(BaseModel):
    user_id: int
    name: str
    description: str

class CreateBacklogPayload(BaseModel):
    user_id: int
    title: str
    tag: str
    priority: str

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

    # Verify acting user has permission to manage roles
    verify_project_permission(project, payload.user_id, "manage_roles")

    if payload.target_user_id not in project.get("members", []):
        raise HTTPException(status_code=404, detail="Target user is not a project member")

    if payload.role_name not in project.get("roles", []):
        raise HTTPException(status_code=422, detail="Invalid role specified")

    # Validate that adding this role doesn't break restriction rules
    validate_role_assignment(project, payload.target_user_id, payload.role_name)

    # Add user to the role list if not already present (allowing multiple roles)
    role_list = project["roles"][payload.role_name]
    if payload.target_user_id not in role_list:
        role_list.append(payload.target_user_id)

    db_manager.write(db)
    return {"status": "success", "message": f"Assigned role '{payload.role_name}' successfully."}

def ensure_member_fields(project: dict) -> None:
    """Backfills `contribute`, roles, permissions, and unified role definitions on projects."""
    members = project.get("members", [])
    if "contribute" not in project:
        project["contribute"] = list(members)
        
    if "roles" not in project:
        creators = [uid for uid in project.get("creator", []) if uid in members]
        project["roles"] = {
            "Project Creator": creators,
            "Project Manager": [],
            "Project Member": [uid for uid in members if uid not in creators],
        }

    # Unify role permissions inside role_definitions if they are separate or missing
    role_permissions = project.get("role_permissions", {})
    definitions = project.setdefault("role_definitions", {
        "Project Creator": {
            "colour": "#44E", 
            "description": "Highest ranking role with full permissions.",
            "permissions": ["add_members", "manage_sprints", "delete_project", "manage_roles"]
        },
        "Project Manager": {
            "colour": "#0ae", 
            "description": "Can manage members and sprints.",
            "permissions": ["add_members", "manage_sprints", "manage_roles"]
        },
        "Project Member": {
            "colour": "#678", 
            "description": "Standard contributor role.",
            "permissions": []
        }
    })

    # Migrate any legacy separate role_permissions into definitions
    for r_name, meta in definitions.items():
        if isinstance(meta, dict) and "permissions" not in meta:
            meta["permissions"] = role_permissions.get(r_name, [])

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
                "description": "Highest ranking role with full permissions.",
                "permissions": ["add_members", "manage_sprints", "delete_project", "manage_roles"]
            },
            "Project Manager": {
                "colour": "#0ae",
                "description": "Can manage members and sprints.",
                "permissions": ["add_members", "manage_sprints", "manage_roles"]
            },
            "Project Member": {
                "colour": "#678",
                "description": "Standard contributor role.",
                "permissions": []
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
    return [p for p in all_projects.values() if user_id in p.get("members", [])]

@router.get("/projects/{project_id}")
def get_project(project_id: int, user_id: int):
    return get_verified_project(project_id, user_id)

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

    item = {
        "id": backlog_id,
        "title": payload.title,
        "tag": payload.tag,
        "priority": payload.priority
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
    
    # Check if the user has the 'add_members' permission, regardless of their role name
    verify_project_permission(project, payload.user_id, "add_members")

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

    # 1. Initialize user list for the new role
    project.setdefault("roles", {})[role_name] = []

    # 2. Register conflict mappings
    if payload.conflicting_roles:
        conflicts = project.setdefault("role_conflicts", {})
        conflicts[role_name] = payload.conflicting_roles
        for conflict_target in payload.conflicting_roles:
            conflicts.setdefault(conflict_target, []).append(role_name)

    # 3. Store unified metadata (colour, description, and permissions together)
    definitions = project.setdefault("role_definitions", {})
    definitions[role_name] = {
        "colour": payload.colour,
        "description": payload.description or "",
        "permissions": payload.permissions
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