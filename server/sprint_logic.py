"""
Pure sprint-date logic (no FastAPI imports) so it can be unit-tested on its own.

Dates are stored as ISO strings ("YYYY-MM-DD"). A sprint covers start_date..end_date
inclusive, and it is automatically completed once today is *after* end_date.
"""
from datetime import date
from typing import Any, Dict, Optional

COLUMNS = ("backlog", "active", "review", "completed")


def today() -> date:
    return date.today()


def parse_date(value: Any, label: str = "Date") -> date:
    """Parse an ISO date string, raising ValueError with a user-friendly message."""
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a valid date (YYYY-MM-DD).")


def validate_sprint_dates(start_value: Any, end_value: Any, today_date: Optional[date] = None):
    """Validate the dates chosen when creating a sprint. Returns (start, end) as dates."""
    today_date = today_date or today()
    start = parse_date(start_value, "Sprint start date")
    end = parse_date(end_value, "Sprint end date")
    if end < start:
        raise ValueError("Sprint end date cannot be before the start date.")
    if end < today_date:
        raise ValueError("Sprint end date cannot be in the past.")
    return start, end


def sprint_bounds(sprint: Dict[str, Any]):
    """(start, end) as dates, or (None, None) for legacy sprints created without dates."""
    try:
        return date.fromisoformat(sprint["start_date"]), date.fromisoformat(sprint["end_date"])
    except (KeyError, TypeError, ValueError):
        return None, None


def auto_complete_sprints(project: Dict[str, Any], today_date: Optional[date] = None) -> bool:
    """End every active sprint whose end date has passed. Returns True if anything changed."""
    today_date = today_date or today()
    changed = False
    for sprint in project.get("sprints", []):
        _, end = sprint_bounds(sprint)
        if end is not None and sprint.get("status") == "active" and today_date > end:
            sprint["status"] = "ended"
            sprint["ended_at"] = end.isoformat()
            sprint["auto_completed"] = True
            changed = True
    return changed


def validate_task_dates(state: Dict[str, Any], sprint: Dict[str, Any]) -> None:
    """Every task start/end date must be valid, ordered, and inside the sprint's dates."""
    s_start, s_end = sprint_bounds(sprint)
    for column in COLUMNS:
        for task in state.get(column, []) or []:
            title = task.get("title", "Task")
            start_raw, end_raw = task.get("start_date"), task.get("end_date")
            start = parse_date(start_raw, f"Start date of '{title}'") if start_raw else None
            end = parse_date(end_raw, f"End date of '{title}'") if end_raw else None
            if start and end and end < start:
                raise ValueError(f"'{title}': end date cannot be before its start date.")
            for label, value in (("start", start), ("end", end)):
                if value is None or s_start is None:
                    continue
                if value < s_start or value > s_end:
                    raise ValueError(
                        f"'{title}': {label} date must be within the sprint "
                        f"({s_start.isoformat()} to {s_end.isoformat()})."
                    )


def stamp_completions(old_state: Dict[str, Any], new_state: Dict[str, Any],
                      sprint: Dict[str, Any], today_date: Optional[date] = None) -> None:
    """
    Record the day each task reached 'completed' (used by the burndown chart).
    The server decides this, never the client: a task keeps its previous completed_at,
    otherwise it gets today's date. Tasks outside 'completed' have it removed.
    """
    today_date = today_date or today()
    s_start, _ = sprint_bounds(sprint)
    previous = {
        str(t.get("id")): t.get("completed_at")
        for t in (old_state or {}).get("completed", []) or []
    }
    legacy_default = (s_start or today_date).isoformat()
    for column in COLUMNS:
        for task in new_state.get(column, []) or []:
            if column == "completed":
                task_id = str(task.get("id"))
                if task_id in previous:
                    task["completed_at"] = previous[task_id] or legacy_default
                else:
                    task["completed_at"] = today_date.isoformat()
            else:
                task.pop("completed_at", None)
