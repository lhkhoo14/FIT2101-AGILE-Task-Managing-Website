"""
Server-backed change history, contribution analytics and work logging.

US-20: the Change History feed and the Member Contribution statistics used to
live in the browser (IndexedDB plus arithmetic done at render time), so they
were different on every device. Both now read and write the project record in
the central database.

US-21: starting and finishing a task writes a work log straight to the server,
stamped with the server's clock and carrying the acting User ID and Task ID, and
the affected contribution figures are recomputed and persisted in the same
transaction.

Every write goes through `db_manager.update()` so the read-modify-write happens
inside one transaction; with the shared connection pool a plain read-then-write
could interleave with another request.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

import contribution_logic as logic
import sprint_logic
from database_manager import db_manager
from dependencies import verify_project_access

router = APIRouter()


def _project_or_404(db: Dict[str, Any], project_id: int, user_id: int) -> Dict[str, Any]:
    return verify_project_access(db.get("projects", {}).get(str(project_id)), user_id)


def _user_or_404(db: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    user = next(
        (u for u in db.get("users", []) if str(u.get("user_id")) == str(user_id)),
        None,
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def refresh_contributions(db: Dict[str, Any], project: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute and persist the project's contribution table. Returns the result.

    Called after every mutation that can change the numbers (a board save, a
    work-log start/stop) so the stored copy is never stale.
    """
    stats = logic.compute_contributions(project, db.get("users", []))
    project["contributions"] = {
        str(entry["user_id"]): entry for entry in stats["members"]
    }
    project["contributions_updated_at"] = logic.utc_stamp()
    return stats


def append_history(project: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    """Append one audit entry to the project, trimming the oldest beyond the cap."""
    entries = project.setdefault("history", [])
    entry = dict(entry)
    entry["id"] = (entries[-1].get("id", 0) + 1) if entries else 1
    entries.append(entry)
    if len(entries) > logic.HISTORY_LIMIT:
        del entries[: len(entries) - logic.HISTORY_LIMIT]
    return entry


class HistoryPayload(BaseModel):
    user_id: int
    action: str = "project_change"
    message: str
    sprint_id: Optional[str] = None
    sprint_name: Optional[str] = None
    task_id: Optional[str] = None
    task_title: Optional[str] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    # Only the one-time browser-data migration sets this; normal writes always
    # use the server clock so the feed cannot be back-dated by a client.
    timestamp: Optional[str] = None


class TimeLogPayload(BaseModel):
    user_id: int
    action: str = Field(description="'start' to open a work session, 'stop' to close it.")


@router.get("/projects/{project_id}/history")
def list_history(project_id: int, user_id: int, limit: int = 200):
    """The project's audit trail, newest first."""
    db = db_manager.read()
    project = _project_or_404(db, project_id, user_id)
    entries = list(project.get("history") or [])
    entries.reverse()
    return entries[: max(1, min(int(limit), logic.HISTORY_LIMIT))]


@router.post("/projects/{project_id}/history", status_code=status.HTTP_201_CREATED)
def add_history(project_id: int, payload: HistoryPayload):
    """Record one change event against the acting user."""

    def mutate(db: Dict[str, Any]) -> Dict[str, Any]:
        project = _project_or_404(db, project_id, payload.user_id)
        actor = _user_or_404(db, payload.user_id)
        entry = append_history(
            project,
            {
                "action": payload.action,
                "message": payload.message,
                "actor": logic.display_name({payload.user_id: actor}, payload.user_id),
                "actor_id": payload.user_id,
                "sprint_id": payload.sprint_id,
                "sprint_name": payload.sprint_name,
                "task_id": payload.task_id,
                "task_title": payload.task_title,
                "from_status": payload.from_status,
                "to_status": payload.to_status,
                "timestamp": payload.timestamp or logic.utc_stamp(),
                "recorded_at": logic.utc_iso(),
            },
        )
        return entry

    return db_manager.update(mutate)


@router.get("/projects/{project_id}/contributions")
def get_contributions(project_id: int, user_id: int):
    """Recompute, persist and return the member contribution statistics.

    Recomputed on read as well as on write so a project whose boards were edited
    before this feature existed gets a populated table on first view.
    """

    def mutate(db: Dict[str, Any]) -> Dict[str, Any]:
        project = _project_or_404(db, project_id, user_id)
        return refresh_contributions(db, project)

    return db_manager.update(mutate)


@router.post("/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/time-log")
def log_task_time(project_id: int, sprint_id: str, task_id: str, payload: TimeLogPayload):
    """Start or stop a work session on a task (US-21).

    The stored session carries the acting User ID, the Task ID and ISO-8601
    start/end stamps taken from the server clock. The project's contribution
    totals are recomputed and saved in the same transaction, and the change is
    written to the audit trail so it appears on every device.
    """
    action = (payload.action or "").strip().lower()
    if action not in ("start", "stop"):
        raise HTTPException(status_code=422, detail="Action must be 'start' or 'stop'.")

    def mutate(db: Dict[str, Any]) -> Dict[str, Any]:
        project = _project_or_404(db, project_id, payload.user_id)
        actor = _user_or_404(db, payload.user_id)
        actor_name = logic.display_name({payload.user_id: actor}, payload.user_id)

        # A sprint whose end date has passed is read-only; settle that first so
        # the status check below sees the current value.
        if sprint_logic.auto_complete_sprints(project):
            project["status_synced_at"] = logic.utc_stamp()

        sprint = next(
            (s for s in project.get("sprints", []) or [] if str(s.get("id")) == str(sprint_id)),
            None,
        )
        if sprint is None:
            raise HTTPException(status_code=404, detail="Sprint not found")

        if sprint.get("status") == "ended":
            raise HTTPException(
                status_code=409,
                detail="This sprint has ended and its time logs can no longer be changed.",
            )

        # US-19: the acting user must belong to the project, and to the sprint
        # when the sprint names its members. Legacy sprints with no member list
        # are open to the whole project.
        sprint_members = [logic.as_id(m) for m in (sprint.get("members") or [])]
        if sprint_members and payload.user_id not in sprint_members:
            raise HTTPException(status_code=403, detail="You are not assigned to this sprint.")

        try:
            task = logic.find_task(project, sprint_id, task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

        moment = logic.utc_now()
        if action == "start":
            entry = logic.start_work_log(task, payload.user_id, moment)
            verb = "started working on"
        else:
            try:
                entry = logic.stop_work_log(task, payload.user_id, moment)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            verb = "stopped working on"

        append_history(
            project,
            {
                "action": "time_log",
                "message": f"{actor_name} {verb} {task.get('title', 'a task')}",
                "actor": actor_name,
                "actor_id": payload.user_id,
                "sprint_id": str(sprint.get("id", "")),
                "sprint_name": sprint.get("name", "Sprint"),
                "task_id": task.get("id"),
                "task_title": task.get("title"),
                "timestamp": logic.utc_stamp(moment),
                "recorded_at": logic.utc_iso(moment),
            },
        )

        stats = refresh_contributions(db, project)
        return {
            "status": "success",
            "action": action,
            "task_id": task.get("id"),
            "work_log": entry,
            "time_log": task.get("time_log") or {},
            "task_seconds": logic.task_seconds(task),
            "contributions": stats,
            "contributions_updated_at": project.get("contributions_updated_at"),
        }

    return db_manager.update(mutate)

