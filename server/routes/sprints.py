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

class DeleteSprintPayload(BaseModel):
    user_id: int

class DeleteTaskPayload(BaseModel):
    user_id: int

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

    # Saving a board replaces the sprint's whole kanban_state, so a card also
    # disappears by simply being left out of the payload. That makes this route a
    # second way to delete a task, so both rules for deletion have to hold here as
    # well: the caller needs manage_tasks, and a completed task - the record of
    # finished work - is never dropped. The diff is taken once, up here, so the two
    # checks and the audit entries below can never disagree about what went.
    previous = sprint.get("kanban_state", {})
    dropped = sprint_logic.removed_tasks(previous, payload.state)

    dropped_completed = [entry for entry in dropped if entry[2] == "completed"]
    if dropped_completed:
        titles = ", ".join(f"'{title}'" for _, title, _ in dropped_completed)
        raise HTTPException(status_code=409, detail=f"A completed task cannot be deleted: {titles}.")

    if dropped:
        verify_project_permission(project, payload.user_id, "manage_tasks")

    try:
        sprint_logic.validate_descriptions(payload.state)
        sprint_logic.validate_task_dates(payload.state, sprint)
        sprint_logic.validate_completion_checklists(previous, payload.state)
        # US-19: refuse a board that assigns work to somebody outside the project.
        sprint_logic.validate_assignees(previous, payload.state, project)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    sprint_logic.stamp_completions(previous, payload.state, sprint)
    sprint["kanban_state"] = payload.state

    # The diff taken before validation is still the diff: stamp_completions only
    # writes fields onto cards that are already on the board, so nothing was added
    # or removed in between and the board does not need walking a second time.
    if dropped:
        actor = actor_label(db, payload.user_id)
        for _, title, column in dropped:
            append_history(project, {
                "action": "deleted_task",
                "message": f"{actor} deleted task {title}",
                "actor": actor,
                "actor_id": payload.user_id,
                "sprint_id": str(sprint.get("id", "")),
                "sprint_name": sprint.get("name", "Sprint"),
                "task_title": title,
                "from_status": column,
            })
    # US-20 / US-21: assigned, completed and logged-time counts are recalculated
    # and stored server-side in the same transaction as the board.
    refresh_contributions(db, project)
    db_manager.write(db)
    return {"status": "success"}


@router.delete("/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}",
               status_code=status.HTTP_200_OK)
def delete_task(project_id: int, sprint_id: str, task_id: str, payload: DeleteTaskPayload):
    """Delete one task from a sprint board.

    Deleting a task requires manage_tasks. Every preset role holds it, so in
    practice any regular member - an Employee included - can delete a task, while a
    custom role can be given the permission or left without it. The one task that
    is kept regardless is one that reached Completed, because that column is the
    record of finished work. The deletion is written to the project's audit trail,
    so it shows up in Change History on every device rather than silently
    vanishing.
    """
    def mutate(db):
        # An overdue sprint counts as ended, so settle that before the checks.
        project = verify_project_access(db.get("projects", {}).get(str(project_id)), payload.user_id)
        # Repair a project stored before roles existed: without a role map the
        # permission check below would refuse every user, the creator included.
        ensure_member_fields(project)
        if sprint_logic.auto_complete_sprints(project):
            project["status_synced_at"] = contribution_logic.utc_stamp()
        # Same repair as _load_project: this route reads the project itself, so
        # the project's leadership is ensured a place on every sprint here too.
        sprint_logic.ensure_leadership_membership(project)
        # Membership is already settled by verify_project_access() above; this adds
        # the manage_tasks requirement on top of it.
        verify_project_permission(project, payload.user_id, "manage_tasks")

        sprint = _find_sprint(project, sprint_id)
        if sprint.get("status") == "ended":
            raise HTTPException(status_code=409, detail="This sprint has ended and can no longer be changed.")

        kanban = sprint.setdefault("kanban_state", dict(EMPTY_KANBAN))
        column, task = sprint_logic.find_board_task(kanban, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found on this sprint's board.")

        blocker = sprint_logic.task_delete_blocker(kanban, task_id)
        if blocker:
            raise HTTPException(status_code=409, detail=blocker)

        wanted = sprint_logic.normalized_task_id(task_id)
        kanban[column] = [
            card for card in kanban.get(column, []) or []
            if sprint_logic.normalized_task_id(card.get("id")) != wanted
        ]

        actor = actor_label(db, payload.user_id)
        append_history(project, {
            "action": "deleted_task",
            "message": f"{actor} deleted task {task.get('title', 'a task')}",
            "actor": actor,
            "actor_id": payload.user_id,
            "sprint_id": str(sprint.get("id", "")),
            "sprint_name": sprint.get("name", "Sprint"),
            "task_id": task.get("id"),
            "task_title": task.get("title"),
            "from_status": column,
        })

        # US-20 / US-21: the task no longer counts towards anybody's figures.
        refresh_contributions(db, project)
        return {
            "status": "success",
            "message": f"Task '{task.get('title', 'Task')}' deleted.",
            "task_id": task.get("id"),
        }

    return db_manager.update(mutate)






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