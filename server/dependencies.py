from fastapi import HTTPException
from typing import Dict, Any
from database_manager import db_manager

# Preset roles a project may only ever have one holder of. The three leadership
# posts are single-seat by definition: a second Project Creator would be a
# second owner, and two Scrum Masters or Product Owners would both be steering
# the same sprint cycle. Manager and Employee stay multi-seat.
#
# src/backend/utils/project_role_helpers.py mirrors this tuple, so the Add
# Member list offers exactly the people this route will accept.
SINGLETON_PRESET_ROLES = ("Project Creator", "Scrum Master", "Product Owner")

def validate_role_assignment(project: dict, user_id: int, target_role: str) -> None:
    """Ensures assigning `target_role` does not violate role restriction rules from unified role_definitions."""
    roles = project.get("roles", {})
    role_definitions = project.get("role_definitions", {})

    # Single-seat presets: refuse a second holder instead of quietly sharing the
    # post. Re-assigning it to whoever already holds it stays a no-op, which is
    # what an idempotent retry looks like.
    if target_role in SINGLETON_PRESET_ROLES:
        other_holders = [
            holder for holder in roles.get(target_role, []) or []
            if str(holder) != str(user_id)
        ]
        if other_holders:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{target_role}' can only be held by one member. "
                    f"Remove the current holder from the role first."
                )
            )

    # Get roles the user currently holds
    current_user_roles = [role for role, uids in roles.items() if user_id in uids]
    
    # Extract conflicting roles for the target role from unified role_definitions
    target_meta = role_definitions.get(target_role, {})
    forbidden_roles = target_meta.get("conflicting_roles", []) if isinstance(target_meta, dict) else []
    
    # Check if any current role conflicts with the target role
    for current_role in current_user_roles:
        if current_role in forbidden_roles:
            raise HTTPException(
                status_code=422,
                detail=f"Conflict: User cannot hold both '{current_role}' and '{target_role}' simultaneously."
            )
        
        # Also check bidirectional conflicts if current roles list them
        current_meta = role_definitions.get(current_role, {})
        current_conflicts = current_meta.get("conflicting_roles", []) if isinstance(current_meta, dict) else []
        if target_role in current_conflicts:
            raise HTTPException(
                status_code=422,
                detail=f"Conflict: User cannot hold both '{current_role}' and '{target_role}' simultaneously."
            )

def verify_project_permission(project: Any, user_id: int, required_permission: str) -> Dict[str, Any]:
    """Enforces that the user has a specific permission based on their assigned role in role_definitions."""
    verify_project_access(project, user_id)
    
    roles = project.get("roles", {})
    role_definitions = project.get("role_definitions", {})
    
    # Find all roles the user belongs to
    user_roles = [role_name for role_name, user_ids in roles.items() if user_id in user_ids]
    
    # Check if any of the user's roles contain the required permission
    has_permission = False
    for role in user_roles:
        def_meta = role_definitions.get(role, {})
        perms = def_meta.get("permissions", []) if isinstance(def_meta, dict) else []
        if required_permission in perms:
            has_permission = True
            break
    
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
