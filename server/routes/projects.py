from typing import Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from database_manager import db_manager
from dependencies import get_verified_project, verify_project_access
import sprint_logic

router = APIRouter()

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

class AddMemberPayload(BaseModel):
    user_id: int
    username: str

def ensure_member_fields(project: dict) -> None:
    """Backfills `contribute` and `roles` on projects created before member roles existed.

    The project creator becomes Product Owner and everyone else a plain Member.
    """
    members = project.get("members", [])
    if "contribute" not in project:
        project["contribute"] = list(members)
    if "roles" not in project:
        owners = [uid for uid in project.get("creator", []) if uid in members]
        project["roles"] = {
            "Product Owner": owners,
            "Scrum Master": [],
            "Member": [uid for uid in members if uid not in owners],
        }

@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectPayload):
    # CHANGE: read the DB once and find the user in it. find_user_by_id() would
    # issue a second read (and a second connection) for data we already have.
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
            "Product Owner": [payload.user_id],
            "Scrum Master": [],
            "Member": []
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
        "roles": project.get("roles", {})
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

    if payload.user_id not in project.get("members", []):
        raise HTTPException(status_code=403, detail="You are not a member of this project")

    member = next(
        (user for user in db.get("users", []) if user.get("username") == payload.username),
        None
    )
    if member is None:
        raise HTTPException(status_code=404, detail="User not found")

    member_id = member["user_id"]
    if member_id in project.get("members", []):
        raise HTTPException(status_code=409, detail="User is already a project member")

    ensure_member_fields(project)
    project["members"].append(member_id)
    project["contribute"].append(member_id)
    project["roles"].setdefault("Member", []).append(member_id)

    db_manager.write(db)

    return {
        "status": "success",
        "member_id": member_id,
        "username": member["username"],
        "role": "Member"
    }
