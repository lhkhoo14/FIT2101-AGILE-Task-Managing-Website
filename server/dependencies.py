from fastapi import HTTPException
from typing import Dict, Any
from database_manager import db_manager

def get_verified_project(project_id: int, user_id: int) -> Dict[str, Any]:
    """Retrieves a project and enforces membership authorization."""
    db = db_manager.read()
    project = db.get("projects", {}).get(str(project_id))

    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if user_id not in project.get("members", []):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: You are not a member of this project"
        )
    return project