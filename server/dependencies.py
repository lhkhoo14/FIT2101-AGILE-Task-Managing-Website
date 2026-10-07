from fastapi import HTTPException
from typing import Dict, Any
from database_manager import db_manager

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
