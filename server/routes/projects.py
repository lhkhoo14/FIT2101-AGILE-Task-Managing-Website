from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from database_manager import db_manager
from dependencies import get_verified_project

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

@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(payload: CreateProjectPayload):
    db = db_manager.read()
    user = db_manager.find_user_by_id(payload.user_id)

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
            "Member": [] },
        "backlog": [],
        "sprints": []
    }

    db["projects"][str(project_id)] = new_project
    user.setdefault("projects", []).append(project_id)
    db_manager.write(db)

    return {"status": "success", "project": new_project}

@router.get("/users/{user_id}/projects")
def get_user_projects(user_id: int):
    db = db_manager.read()
    user = db_manager.find_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    all_projects = db.get("projects", {})
    return [p for p in all_projects.values() if user_id in p.get("members", [])]

@router.get("/projects/{project_id}")
def get_project(project_id: int, user_id: int):
    return get_verified_project(project_id, user_id)

@router.get("/projects/{project_id}/members")
def get_project_members(project_id: int, user_id: int):
    project = get_verified_project(project_id, user_id)

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
    get_verified_project(project_id, payload.user_id)
    
    db = db_manager.read()
    project = db["projects"][str(project_id)]

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
        raise HTTPException(
            status_code=404,
            detail="Project not found"
        )

    if payload.user_id not in project.get("members", []):
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this project"
        )

    member = next(
        (
            user
            for user in db.get("users", [])
            if user.get("username") == payload.username
        ),
        None
    )

    if member is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    member_id = member["user_id"]

    if member_id in project.get("members", []):
        raise HTTPException(
            status_code=409,
            detail="User is already a project member"
        )

    project.setdefault("members", []).append(member_id)
    project.setdefault("contribute", []).append(member_id)

    roles = project.setdefault(
        "roles",
        {
            "Product Owner": [],
            "Scrum Master": [],
            "Member": []
        }
    )

    roles.setdefault("Member", []).append(member_id)

    db_manager.write(db)

    return {
        "status": "success",
        "member_id": member_id,
        "username": member["username"],
        "role": "Member"
    }