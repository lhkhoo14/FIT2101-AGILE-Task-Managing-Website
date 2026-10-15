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
                if value is None or s_start is None or s_end is None:
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
        return []

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


# ---------------------------------------------------------------------------
# Project leadership is part of every sprint
# ---------------------------------------------------------------------------
# CHANGE: the three roles that own the sprint cycle are now members of every
# sprint in their project. "Only assigned members can open this sprint" makes
# that necessary: a Project Creator, Scrum Master or Product Owner who was not
# ticked in the create-sprint dialog could not open the boards they are
# responsible for, and so could not manage the sprint (or delete it) at all.
# Manager is deliberately not here - it manages sprints but is staffed in like
# anyone else - so this list is exactly "who owns the project's sprints".
LEADERSHIP_ROLES = ("Project Creator", "Scrum Master", "Product Owner")


def leadership_member_ids(project: Dict[str, Any]) -> list:
    """Member ids holding a project-leadership role, in role order, de-duplicated.

    Read from the project's role map, so it follows whatever the Roles page has
    assigned and is empty for a project with no role map yet.
    """
    roles = project.get("roles") or {}
    leaders = []
    for role_name in LEADERSHIP_ROLES:
        for holder in roles.get(role_name) or []:
            try:
                value = int(str(holder).strip())
            except (TypeError, ValueError):
                continue
            if value not in leaders:
                leaders.append(value)
    return leaders


def ensure_leadership_membership(project: Dict[str, Any]) -> bool:
    """Add the project's leadership to every sprint's member list.

    Returns True if anything changed, so callers can persist the repair. A
    legacy sprint whose "members" is None is left alone: None already means
    "the whole project", which includes the leadership. Idempotent, and it only
    ever adds project members, so US-19 (sprint members must belong to the
    project) still holds afterwards.
    """
    leaders = leadership_member_ids(project)
    if not leaders:
        return False
    changed = False
    for sprint in project.get("sprints", []) or []:
        members = sprint.get("members")
        if members is None:
            continue
        current = []
        for raw in members:
            try:
                value = int(str(raw).strip())
            except (TypeError, ValueError):
                continue
            if value not in current:
                current.append(value)
        missing = [leader for leader in leaders if leader not in current]
        if missing:
            sprint["members"] = current + missing
            changed = True
    return changed


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


# ---------------------------------------------------------------------------
# Task descriptions
# ---------------------------------------------------------------------------
MAX_DESCRIPTION_LENGTH = 1000


def clean_description(raw: Any) -> str:
    """A description as stored: surrounding whitespace removed, "" when absent."""
    return raw.strip() if isinstance(raw, str) else ""


def validate_descriptions(state: Dict[str, Any]) -> None:
    """Every task description must be text no longer than MAX_DESCRIPTION_LENGTH."""
    for column in COLUMNS:
        for task in state.get(column, []) or []:
            description = task.get("description")
            if description is None:
                continue
            title = task.get("title", "Task")
            if not isinstance(description, str):
                raise ValueError(f"The description of '{title}' must be text.")
            if len(description) > MAX_DESCRIPTION_LENGTH:
                raise ValueError(
                    f"The description of '{title}' is too long "
                    f"(maximum {MAX_DESCRIPTION_LENGTH} characters)."
                )


def descriptions_changed(old_state: Dict[str, Any], new_state: Dict[str, Any]) -> bool:
    """True if saving new_state would add, edit or remove any task description."""
    def by_id(state):
        return {
            str(task.get("id")): clean_description(task.get("description"))
            for column in COLUMNS
            for task in (state or {}).get(column, []) or []
        }
    old, new = by_id(old_state), by_id(new_state)
    return any(text != old.get(task_id, "") for task_id, text in new.items())


# ---------------------------------------------------------------------------
# Task deletion
# ---------------------------------------------------------------------------
def find_board_task(state: Dict[str, Any], task_id: Any):
    """(column, card) for a task on a board, or (None, None) when it is absent."""
    wanted = normalized_task_id(task_id)
    for column in COLUMNS:
        for task in (state or {}).get(column, []) or []:
            if normalized_task_id(task.get("id")) == wanted:
                return column, task
    return None, None


def task_delete_blocker(state: Dict[str, Any], task_id: Any) -> Optional[str]:
    """Why this task may not be deleted, or None when it may be.

    A task that reached Completed is the record of finished work, so it is kept;
    every other task can go. save_kanban_state() applies the same rule to a board
    save by diffing the incoming board against the stored one, so the rule cannot
    be sidestepped by leaving a card out of a payload.
    """
    column, _ = find_board_task(state, task_id)
    if column is None:
        return "Task not found on this sprint's board."
    if column == "completed":
        return "A completed task cannot be deleted."
    return None


def removed_tasks(old_state: Dict[str, Any], new_state: Dict[str, Any]) -> list:
    """(task_id, title, column) for every card a new board leaves out.

    Saving a board replaces the sprint's whole kanban_state, so a card disappears
    simply by being absent from the payload. Deletion is therefore detected by
    diffing the stored board against the incoming one, the same way
    descriptions_changed detects an edit.
    """
    remaining = {
        normalized_task_id(task.get("id"))
        for column in COLUMNS
        for task in (new_state or {}).get(column, []) or []
    }
    gone = []
    for column in COLUMNS:
        for task in (old_state or {}).get(column, []) or []:
            task_id = normalized_task_id(task.get("id"))
            if task_id not in remaining:
                gone.append((task_id, task.get("title", "Task"), column))
    return gone
