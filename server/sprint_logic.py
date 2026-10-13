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


def unchecked_checklist_items(task: Dict[str, Any]) -> list:
    """Checklist items on a task that have not been ticked off yet."""
    return [item for item in (task.get("checklist") or []) if not item.get("done")]


def validate_completion_checklists(old_state: Dict[str, Any], new_state: Dict[str, Any]) -> None:
    """
    A task may only ENTER 'completed' once every checklist item is ticked off.
    Tasks that were already completed before this save are left alone (legacy data).
    Enforced here so the rule holds no matter which client sends the board.
    """
    already_completed = {
        str(t.get("id")) for t in (old_state or {}).get("completed", []) or []
    }
    for task in new_state.get("completed", []) or []:
        if str(task.get("id")) in already_completed:
            continue
        pending = unchecked_checklist_items(task)
        if pending:
            title = task.get("title", "Task")
            noun = "item" if len(pending) == 1 else "items"
            raise ValueError(
                f"'{title}' still has {len(pending)} unchecked checklist {noun}. "
                "Tick them all off before moving it to Completed."
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


def _member_id_set(project: Dict[str, Any]) -> set:
    ids = set()
    for raw in project.get("members", []) or []:
        text = str(raw).strip()
        if text.lstrip("-").isdigit():
            ids.add(int(text))
    return ids


def validate_sprint_members(members: Optional[list], project: Dict[str, Any]) -> list:
    """US-19: a sprint may only be staffed with members of its parent project.

    Returns the de-duplicated member list (order preserved) or raises ValueError
    naming the users that do not belong to the project. `None` is left alone
    because legacy sprints use it to mean "the whole project".
    """
    if members is None:
        return None

    project_members = _member_id_set(project)
    cleaned = []
    rejected = []
    for raw in members:
        text = str(raw).strip()
        if not text.lstrip("-").isdigit():
            rejected.append(str(raw))
            continue
        value = int(text)
        if value not in project_members:
            rejected.append(str(value))
            continue
        if value not in cleaned:
            cleaned.append(value)

    if rejected:
        raise ValueError(
            "Only members of this project can be assigned to a sprint. "
            f"Not a project member: {', '.join(rejected)}."
        )
    return cleaned


def validate_assignees(old_state: Dict[str, Any], new_state: Dict[str, Any],
                      project: Dict[str, Any]) -> None:
    """US-19: reject a board save that assigns a task to a non-project member.

    Only tasks whose assignee actually changed are checked, so a board holding a
    task assigned to someone who has since left the project can still be saved
    (the untouched task keeps its legacy assignee).
    """
    project_members = _member_id_set(project)
    previous = {}
    for column in COLUMNS:
        for task in (old_state or {}).get(column, []) or []:
            previous[str(task.get("id"))] = task.get("assignee_id")

    for column in COLUMNS:
        for task in (new_state or {}).get(column, []) or []:
            assignee_id = task.get("assignee_id")
            if assignee_id is None:
                continue
            if previous.get(str(task.get("id"))) == assignee_id:
                continue
            title = task.get("title", "Task")
            text = str(assignee_id).strip()
            if not text.lstrip("-").isdigit():
                raise ValueError(f"'{title}' has an invalid assignee.")
            if int(text) not in project_members:
                raise ValueError(
                    f"'{title}' cannot be assigned to user {text}: they are not a "
                    "member of this project."
                )



# ---------------------------------------------------------------------------
# Task tags and returning tasks to the product backlog
# ---------------------------------------------------------------------------
MAX_TAGS = 10
MAX_TAG_LENGTH = 20


def normalize_tags(raw) -> list:
    """Turn user input ("Frontend, #API ,, urgent") into a clean tag list.

    Mirrors the browser-side helper in src/backend/sprint_access.py so the API
    stores the same tags whichever client sent them: lowercased, a leading "#"
    removed, de-duplicated (order kept), capped in length and in number.
    """
    if raw is None:
        return []
    parts = raw.split(",") if isinstance(raw, str) else list(raw)
    tags = []
    for part in parts:
        tag = " ".join(str(part).strip().lstrip("#").split()).lower()[:MAX_TAG_LENGTH].strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags[:MAX_TAGS]


def task_tags(task: Dict[str, Any]) -> list:
    """Tags on a task card or backlog item.

    Items saved before tasks had several tags carry a single "tag" string; it is
    read as a one-item list so old data keeps its tag without a migration.
    """
    tags = task.get("tags")
    return normalize_tags(tags if tags is not None else task.get("tag"))


def is_sprint_member(sprint: Dict[str, Any], user_id: Any) -> bool:
    """True if the user is assigned to the sprint.

    Legacy sprints saved before members existed have no "members" key and stay
    open to everyone; a sprint with an explicit (even empty) list is restricted.
    """
    members = sprint.get("members")
    if members is None:
        return True
    try:
        uid = int(user_id)
        return uid in {int(m) for m in members}
    except (TypeError, ValueError):
        return False


def normalized_task_id(task_id: Any) -> str:
    """Board cards are named "task-<backlog id>"; strip the prefix for comparisons."""
    text = str(task_id or "")
    return text[5:] if text.startswith("task-") else text


def has_logged_work(task: Dict[str, Any]) -> bool:
    """True once someone has started the task's timer (work time has been recorded)."""
    time_log = task.get("time_log") or {}
    return bool(time_log.get("started_at") or time_log.get("entries"))


def backlog_id_for_task(task: Dict[str, Any], taken_ids: set, fallback_id: int):
    """The product-backlog id a returned task goes back under: (id, used_fallback).

    A card made from a backlog item is named "task-<backlog id>", so its original
    id is restored when it is still free. Otherwise the fallback (a fresh id) is
    used so two backlog items can never share an id.
    """
    raw = normalized_task_id(task.get("id"))
    if raw.isdigit() and int(raw) not in taken_ids:
        return int(raw), False
    return fallback_id, True
