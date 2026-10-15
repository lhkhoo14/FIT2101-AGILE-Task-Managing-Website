from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from database_manager import db_manager
from dependencies import verify_project_access, verify_project_permission
from routes.activity import actor_label, append_history, refresh_contributions
# ensure_member_fields() is the one place a project's role map is built, and it is
# what guarantees role_definitions exists before a permission is checked. Sprint
# routes can be the first request to touch a project, so they need it too.
from routes.projects import ensure_member_fields
import logic.contribution_logic as contribution_logic
import logic.sprint_logic as sprint_logic

router = APIRouter()

EMPTY_KANBAN = {"backlog": [], "active": [], "review": [], "completed": []}


def _load_project(project_id: int, user_id: int):
    """
    Verify membership, then load the DB with overdue sprints automatically completed.
    Returns (db, project). The DB is written back only if something in the project
    had to be repaired (an auto-completed sprint, or a sprint the project's
    leadership was missing from).
    """
    # CHANGE: read the database exactly once. This used to call
    # get_verified_project() (which reads) and then read again, costing two
    # connections per sprint request.
    db = db_manager.read()
    project = verify_project_access(db.get("projects", {}).get(str(project_id)), user_id)
    # A project stored before roles existed has no usable role map, and this is the
    # first place a sprint request touches it. Normalising here means the
    # verify_project_permission() calls that follow (here and in the board save)
    # see roles instead of refusing every user. A read-only request only repairs
    # the copy it returns; the next write to this project persists the repair.
    ensure_member_fields(project)
    # CHANGE: a sprint stored before its project's leadership was assigned is
    # repaired here as well, and this time written back. Otherwise a Project
    # Creator / Scrum Master / Product Owner opening such a sprint would be
    # turned away by the "members only" check that every sprint view and every
    # sprint route applies, with no way to fix it from the UI.
    stale_leadership = sprint_logic.ensure_leadership_membership(project)
    if sprint_logic.auto_complete_sprints(project) or stale_leadership:
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

class ReturnTaskPayload(BaseModel):
    user_id: int

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

    # CHANGE: the project's leadership (Project Creator, Scrum Master, Product
    # Owner) is added to every sprint, whether or not the dialog ticked them.
    # They are the roles that own the sprint cycle, and sprint access is
    # members-only, so a leader left out here could not open the board they are
    # responsible for. Added after validation, so they are still project
    # members, and in role order so the list reads predictably.
    for leader in sprint_logic.leadership_member_ids(project):
        if leader not in members:
            members.append(leader)

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
    # US-20: keep the stored contribution table present from the start.
    refresh_contributions(db, project)
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

    # Task descriptions can be added and edited by the sprint's members only.
    if (sprint_logic.descriptions_changed(sprint.get("kanban_state", {}), payload.state)
            and not sprint_logic.is_sprint_member(sprint, payload.user_id)):
        raise HTTPException(status_code=403, detail="Only members of this sprint can edit task descriptions.")

    try:
        sprint_logic.validate_descriptions(payload.state)
        sprint_logic.validate_task_dates(payload.state, sprint)
        sprint_logic.validate_completion_checklists(sprint.get("kanban_state", {}), payload.state)
        # US-19: refuse a board that assigns work to somebody outside the project.
        sprint_logic.validate_assignees(sprint.get("kanban_state", {}), payload.state, project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sprint_logic.stamp_completions(sprint.get("kanban_state", {}), payload.state, sprint)
    sprint["kanban_state"] = payload.state
    # US-20 / US-21: assigned, completed and logged-time counts are recalculated
    # and stored server-side in the same transaction as the board.
    refresh_contributions(db, project)
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
        "tags": sprint_logic.task_tags(item),
        "description": sprint_logic.clean_description(item.get("description")),
        "priority": item["priority"],
        "assignee": None,
        "start_date": None,
        "end_date": None
    }
    kanban.setdefault("backlog", []).append(task_card)
    
    refresh_contributions(db, project)
    db_manager.write(db)
    return {"status": "success"}

@router.post("/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/return-to-backlog")
def return_task_to_product_backlog(project_id: int, sprint_id: str, task_id: str, payload: ReturnTaskPayload):
    """Move a task that is still in the sprint's Backlog column back to the product backlog.

    The reverse of move_backlog_to_sprint. Only tasks nobody has started working
    on can go back: once a task has left the sprint backlog, or has logged work
    time, returning it would discard progress, so it is refused.
    """
    db, project = _load_project(project_id, payload.user_id)
    sprint = _find_sprint(project, sprint_id)

    if not sprint_logic.is_sprint_member(sprint, payload.user_id):
        raise HTTPException(status_code=403, detail="You are not assigned to this sprint.")
    if sprint.get("status") == "ended":
        raise HTTPException(status_code=409, detail="This sprint has ended and can no longer be changed.")

    kanban = sprint.setdefault("kanban_state", {
        "backlog": [],
        "active": [],
        "review": [],
        "completed": []
    })
    wanted = sprint_logic.normalized_task_id(task_id)

    def matches(card):
        return sprint_logic.normalized_task_id(card.get("id")) == wanted

    sprint_backlog = kanban.setdefault("backlog", [])
    task = next((card for card in sprint_backlog if matches(card)), None)
    if task is None:
        started = any(
            matches(card)
            for column, cards in kanban.items() if column != "backlog"
            for card in cards or []
        )
        if started:
            raise HTTPException(
                status_code=409,
                detail="Only tasks still in the sprint backlog can be returned to the product backlog."
            )
        raise HTTPException(status_code=404, detail="Task not found in this sprint")

    if sprint_logic.has_logged_work(task):
        raise HTTPException(
            status_code=409,
            detail="This task has logged work time, so it can't be returned to the product backlog."
        )

    product_backlog = project.setdefault("backlog", [])
    taken_ids = {int(entry["id"]) for entry in product_backlog if str(entry.get("id")).isdigit()}
    fresh_id = max(db.get("next_backlog_id", 1), max(taken_ids, default=0) + 1)
    backlog_id, used_fresh_id = sprint_logic.backlog_id_for_task(task, taken_ids, fresh_id)
    if used_fresh_id:
        db["next_backlog_id"] = fresh_id + 1

    # Only what a product-backlog item holds goes back (including its description);
    # sprint-specific details (checklist, assignee, dates, feedback) stay behind.
    item = {
        "id": backlog_id,
        "title": task.get("title", "Untitled task"),
        "tags": sprint_logic.task_tags(task),
        "priority": task.get("priority", "medium"),
        "description": sprint_logic.clean_description(task.get("description"))
    }
    sprint_backlog.remove(task)
    product_backlog.append(item)

    refresh_contributions(db, project)
    db_manager.write(db)
    return {"status": "success", "backlog_item": item}

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