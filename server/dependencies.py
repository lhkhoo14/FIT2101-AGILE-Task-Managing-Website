from fastapi import HTTPException
from typing import Dict, Any
from database_manager import db_manager

def validate_role_assignment(project: dict, user_id: int, target_role: str) -> None:
    """Ensures assigning `target_role` does not violate role restriction rules."""
    roles = project.get("roles", {})
    conflicts = project.get("role_conflicts", {})
    
    # Get roles the user currently holds
    current_user_roles = [role for role, uids in roles.items() if user_id in uids]
    
    # Check if any current role conflicts with the target role
    forbidden_roles = conflicts.get(target_role, [])
    for current_role in current_user_roles:
        if current_role in forbidden_roles:
            raise HTTPException(
                status_code=422,
                detail=f"Conflict: User cannot hold both '{current_role}' and '{target_role}' simultaneously."
            )

def verify_project_creator(project: Any, user_id: int) -> Dict[str, Any]:
    """Ensures the user is the Project Creator."""
    verify_project_access(project, user_id)
    roles = project.get("roles", {})
    creators = roles.get("Project Creator", project.get("creator", [])) # Updated key
    if user_id not in creators:
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: Only the Project Creator can perform this action"
        )
    return project

def verify_project_permission(project: Any, user_id: int, required_permission: str) -> Dict[str, Any]:
    """Enforces that the user has a specific permission based on their assigned role."""
    verify_project_access(project, user_id)
    
    roles = project.get("roles", {})
    role_permissions = project.get("role_permissions", {})
    
    # Find all roles the user belongs to
    user_roles = [role_name for role_name, user_ids in roles.items() if user_id in user_ids]
    
    # Check if any of the user's roles contain the required permission
    has_permission = any(
        required_permission in role_permissions.get(role, [])
        for role in user_roles
    )
    
    if not has_permission:
        raise HTTPException(
            status_code=403,
            detail=f"Access forbidden: Missing required permission '{required_permission}'"
        )
    return project

def verify_project_access(project: Any, user_id: int) -> Dict[str, Any]:
    """Enforce membership authorization on a project already loaded from the DB.

    Split out from `get_verified_project` so callers that have already read the
    database can check access without paying for a second read.
    """
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if user_id not in project.get("members", []):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: You are not a member of this project"
        )
    return project

def get_verified_project(project_id: int, user_id: int) -> Dict[str, Any]:
    """Retrieves a project and enforces membership authorization."""
    db = db_manager.read()
    return verify_project_access(db.get("projects", {}).get(str(project_id)), user_id)
