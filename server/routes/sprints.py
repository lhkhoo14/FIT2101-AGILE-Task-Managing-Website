from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from database_manager import db_manager
from dependencies import get_verified_project

router = APIRouter()

class CreateSprintPayload(BaseModel):
    user_id: int
    name: str
    details: str
    status: str

class MoveBacklogPayload(BaseModel):
    user_id: int
    backlog_id: int

class SaveKanbanStatePayload(BaseModel):
    user_id: int
    state: dict

class UpdateSprintStatusPayload(BaseModel):
    user_id: int
    status: str

@router.get("/projects/{project_id}/sprints")
def get_project_sprints(project_id: int, user_id: int):
    project = get_verified_project(project_id, user_id)
    return project.get("sprints", [])

@router.post("/projects/{project_id}/sprints", status_code=status.HTTP_201_CREATED)
def create_sprint(project_id: int, payload: CreateSprintPayload):
    get_verified_project(project_id, payload.user_id)
    
    db = db_manager.read()
    project = db["projects"][str(project_id)]

    sprint_id = db.get("next_sprint_id", 1)
    db["next_sprint_id"] = sprint_id + 1

    sprint = {
        "id": str(sprint_id),
        "name": payload.name,
        "details": payload.details,
        "status": payload.status,
        "kanban_state": {
            "backlog": [],
            "active": [],
            "review": [],
            "completed": []
        }
    }
    project.setdefault("sprints", []).append(sprint)
    db_manager.write(db)
    return sprint

@router.get("/projects/{project_id}/sprints/{sprint_id}")
def get_sprint(project_id: int, sprint_id: str, user_id: int):
    project = get_verified_project(project_id, user_id)
    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint

@router.patch("/projects/{project_id}/sprints/{sprint_id}/status")
def update_sprint_status(project_id: int, sprint_id: str, payload: UpdateSprintStatusPayload):
    get_verified_project(project_id, payload.user_id)
    
    db = db_manager.read()
    project = db["projects"][str(project_id)]

    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")

    sprint["status"] = payload.status
    db_manager.write(db)
    return {"status": "success", "sprint": sprint}

@router.get("/projects/{project_id}/sprints/{sprint_id}/kanban")
def get_kanban_state(project_id: int, sprint_id: str, user_id: int):
    sprint = get_sprint(project_id, sprint_id, user_id)
    return sprint.get("kanban_state", {
        "backlog": [],
        "active": [],
        "review": [],
        "completed": []
    })

@router.put("/projects/{project_id}/sprints/{sprint_id}/kanban")
def save_kanban_state(project_id: int, sprint_id: str, payload: SaveKanbanStatePayload):
    get_verified_project(project_id, payload.user_id)

    db = db_manager.read()
    project = db["projects"][str(project_id)]

    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")

    sprint["kanban_state"] = payload.state
    db_manager.write(db)
    return {"status": "success"}

@router.post("/projects/{project_id}/sprints/{sprint_id}/backlog")
def move_backlog_to_sprint(project_id: int, sprint_id: str, payload: MoveBacklogPayload):
    get_verified_project(project_id, payload.user_id)

    db = db_manager.read()
    project = db["projects"][str(project_id)]

    backlog = project.get("backlog", [])
    item_idx = next((i for i, item in enumerate(backlog) if str(item["id"]) == str(payload.backlog_id)), None)
    if item_idx is None:
        raise HTTPException(status_code=404, detail="Backlog item not found in project backlog")

    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")

    item = backlog.pop(item_idx)
    kanban = sprint.setdefault("kanban_state", {
        "backlog": [],
        "active": [],
        "review": [],
        "completed": []
    })

    task_card = {
        "id": f"task-{item['id']}",
        "title": item["title"],
        "tag": item["tag"],
        "priority": item["priority"],
        "assignee": None
    }
    kanban.setdefault("backlog", []).append(task_card)
    
    db_manager.write(db)
    return {"status": "success"}

@router.get("/projects/{project_id}/sprints/{sprint_id}/backlog")
def get_sprint_backlog(project_id: int, sprint_id: str, user_id: int):
    sprint = get_sprint(project_id, sprint_id, user_id)
    kanban = sprint.get("kanban_state", {
        "backlog": [],
        "active": [],
        "review": [],
        "completed": []
    })
    
    # Flatten items from all kanban columns into a single list with a status field
    items = []
    for column, tasks in kanban.items():
        for task in tasks:
            task_item = dict(task)
            task_item["status"] = column
            items.append(task_item)
    return items