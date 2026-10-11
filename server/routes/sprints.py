from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from database_manager import db_manager
from dependencies import verify_project_access
import sprint_logic

router = APIRouter()

EMPTY_KANBAN = {"backlog": [], "active": [], "review": [], "completed": []}


def _load_project(project_id: int, user_id: int):
    """
    Verify membership, then load the DB with overdue sprints automatically completed.
    Returns (db, project). The DB is written back only if a sprint was auto-completed.
    """
    # CHANGE: read the database exactly once. This used to call
    # get_verified_project() (which reads) and then read again, costing two
    # connections per sprint request.
    db = db_manager.read()
    project = verify_project_access(db.get("projects", {}).get(str(project_id)), user_id)
    if sprint_logic.auto_complete_sprints(project):
        db_manager.write(db)
    return db, project


def _find_sprint(project, sprint_id):
    sprint = next((s for s in project.get("sprints", []) if str(s["id"]) == str(sprint_id)), None)
    if not sprint:
        raise HTTPException(status_code=404, detail="Sprint not found")
    return sprint

class CreateSprintPayload(BaseModel):
    user_id: int
    name: str
    details: str
    status: str
    start_date: str
    end_date: str
    priority: str = "medium"
    tags: list[str] = Field(default_factory=list)
    members: list[int] | None = None
    created_at: int | None = None

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
    _, project = _load_project(project_id, user_id)
    return project.get("sprints", [])

@router.post("/projects/{project_id}/sprints", status_code=status.HTTP_201_CREATED)
def create_sprint(project_id: int, payload: CreateSprintPayload):
    try:
        start, end = sprint_logic.validate_sprint_dates(payload.start_date, payload.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    db, project = _load_project(project_id, payload.user_id)

    # US-19: a sprint may only be staffed with members of its parent project, so
    # a client cannot slip an unrelated account in through the API payload.
    try:
        members = sprint_logic.validate_sprint_members(payload.members, project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sprint_id = db.get("next_sprint_id", 1)
    db["next_sprint_id"] = sprint_id + 1

    sprint = {
        "id": str(sprint_id),
        "name": payload.name,
        "details": payload.details,
        "status": payload.status,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "priority": payload.priority,
        "tags": payload.tags,
        "members": members,
        "created_by": payload.user_id,
        "created_at": payload.created_at,
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
    _, project = _load_project(project_id, user_id)
    return _find_sprint(project, sprint_id)

@router.patch("/projects/{project_id}/sprints/{sprint_id}/status")
def update_sprint_status(project_id: int, sprint_id: str, payload: UpdateSprintStatusPayload):
    if payload.status not in ("active", "ended"):
        raise HTTPException(status_code=422, detail="Status must be 'active' or 'ended'.")

    db, project = _load_project(project_id, payload.user_id)
    sprint = _find_sprint(project, sprint_id)

    if sprint.get("status") == "ended" and payload.status == "active":
        raise HTTPException(status_code=409, detail="An ended sprint cannot be reopened.")

    sprint["status"] = payload.status
    if payload.status == "ended":
        sprint.setdefault("ended_at", sprint_logic.today().isoformat())
    db_manager.write(db)
    return {"status": "success", "sprint": sprint}

@router.get("/projects/{project_id}/sprints/{sprint_id}/kanban")
def get_kanban_state(project_id: int, sprint_id: str, user_id: int):
    sprint = get_sprint(project_id, sprint_id, user_id)
    return sprint.get("kanban_state", dict(EMPTY_KANBAN))

@router.get("/projects/{project_id}/kanban-states")
def get_all_kanban_states(project_id: int, user_id: int):
    """Every sprint's board for this project, keyed by sprint id.

    CHANGE: batch endpoint. The dashboard used to call the per-sprint kanban
    route once per sprint, so a project with 10 sprints cost 10 round trips
    (and 10 authorization reads). This returns all of them from one read.
    """
    _, project = _load_project(project_id, user_id)
    return {
        str(sprint["id"]): sprint.get("kanban_state") or dict(EMPTY_KANBAN)
        for sprint in project.get("sprints", [])
    }

@router.put("/projects/{project_id}/sprints/{sprint_id}/kanban")
def save_kanban_state(project_id: int, sprint_id: str, payload: SaveKanbanStatePayload):
    db, project = _load_project(project_id, payload.user_id)
    sprint = _find_sprint(project, sprint_id)

    if sprint.get("status") == "ended":
        raise HTTPException(status_code=409, detail="This sprint has ended and can no longer be changed.")

    try:
        sprint_logic.validate_task_dates(payload.state, sprint)
        sprint_logic.validate_completion_checklists(sprint.get("kanban_state", {}), payload.state)
        # US-19: refuse a board that assigns work to somebody outside the project.
        sprint_logic.validate_assignees(sprint.get("kanban_state", {}), payload.state, project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sprint_logic.stamp_completions(sprint.get("kanban_state", {}), payload.state, sprint)
    sprint["kanban_state"] = payload.state
    db_manager.write(db)
    return {"status": "success"}

@router.post("/projects/{project_id}/sprints/{sprint_id}/backlog")
def move_backlog_to_sprint(project_id: int, sprint_id: str, payload: MoveBacklogPayload):
    db, project = _load_project(project_id, payload.user_id)

    backlog = project.get("backlog", [])
    item_idx = next((i for i, item in enumerate(backlog) if str(item["id"]) == str(payload.backlog_id)), None)
    if item_idx is None:
        raise HTTPException(status_code=404, detail="Backlog item not found in project backlog")

    sprint = _find_sprint(project, sprint_id)
    if sprint.get("status") == "ended":
        raise HTTPException(status_code=409, detail="This sprint has ended; tasks can no longer be added.")

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
        "assignee": None,
        "start_date": None,
        "end_date": None
    }
    kanban.setdefault("backlog", []).append(task_card)
    
    db_manager.write(db)
    return {"status": "success"}

@router.get("/projects/{project_id}/sprints/{sprint_id}/backlog")
def get_sprint_backlog(project_id: int, sprint_id: str, user_id: int):
    sprint = get_sprint(project_id, sprint_id, user_id)
    kanban = sprint.get("kanban_state", dict(EMPTY_KANBAN))

    # Flatten items from all kanban columns into a single list with a status field
    items = []
    for column, tasks in kanban.items():
        for task in tasks:
            task_item = dict(task)
            task_item["status"] = column
            items.append(task_item)
    return items