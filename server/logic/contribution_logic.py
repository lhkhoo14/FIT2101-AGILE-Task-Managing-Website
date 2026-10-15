"""
Pure change-history and contribution logic (no FastAPI imports) so it can be
unit-tested on its own.

US-20 / US-21: change history, member contribution statistics and per-task work
logs are owned by the server. Everything in here works on plain dicts taken
straight out of `application_state`, so the same functions serve the API routes
and any migration/seeding path.

Timestamps are ISO-8601 UTC strings produced by the *server*, never by the
client: a work log has to mean the same thing on every device.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

COLUMNS = ("backlog", "active", "review", "completed")

# Keeps one project's audit trail from growing without bound inside the single
# JSON row the application state lives in. Oldest entries are dropped first.
HISTORY_LIMIT = 500


# ------------------------------------------------------------------ timestamps
def utc_now() -> datetime:
    """Timezone-aware 'now', so every stored stamp is directly comparable."""
    return datetime.now(timezone.utc)


def utc_stamp(moment: Optional[datetime] = None) -> str:
    """Human-readable stamp used for the activity feed."""
    return (moment or utc_now()).strftime("%Y-%m-%d %H:%M UTC")


def utc_iso(moment: Optional[datetime] = None) -> str:
    """Machine-readable stamp used for work-log start/end pairs."""
    return (moment or utc_now()).isoformat()


# -------------------------------------------------------------------- members
def as_id(value: Any) -> Optional[int]:
    """Coerce a stored member/user reference to int, or None when it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.lstrip("-").isdigit():
        return int(text)
    return None


def member_ids(project: Dict[str, Any]) -> List[int]:
    """Project member ids, in the order the project stores them."""
    ids: List[int] = []
    for raw in project.get("members", []) or []:
        parsed = as_id(raw)
        if parsed is not None and parsed not in ids:
            ids.append(parsed)
    return ids


def name_to_id_map(users: Iterable[Dict[str, Any]], allowed_ids: Iterable[int]) -> Dict[str, int]:
    """Map every username and email of an allowed member to its id.

    Keys are case-folded so `resolve_owner` can match without caring about case.
    """
    allowed = set(allowed_ids)
    mapping: Dict[str, int] = {}
    for user in users or []:
        user_id = as_id(user.get("user_id"))
        if user_id is None or user_id not in allowed:
            continue
        for field in ("username", "email"):
            value = (user.get(field) or "").strip()
            if value:
                mapping.setdefault(value.casefold(), user_id)
    return mapping


def display_name(users_by_id: Dict[int, Dict[str, Any]], user_id: int) -> str:
    user = users_by_id.get(user_id) or {}
    return user.get("username") or user.get("email") or f"User {user_id}"


def _match_owner(name: str, mapping: Dict[str, int]) -> Optional[int]:
    """Resolve an assignee string to a member id.

    Mirrors the abbreviation handling the dashboard used to do in the browser:
    seeded data stores "John" where the account is "John Smith", so an exact
    match is tried first and a "<something> John" suffix match second.
    """
    normalized = (name or "").strip().casefold()
    if not normalized:
        return None
    direct = mapping.get(normalized)
    if direct is not None:
        return direct
    for candidate, user_id in mapping.items():
        if candidate.endswith(f" {normalized}"):
            return user_id
    return None


def resolve_owner(
    task: Dict[str, Any], allowed_ids: Iterable[int], mapping: Dict[str, int]
) -> Optional[int]:
    """Which project member a task belongs to, or None when unassigned/outside."""
    allowed = set(allowed_ids)
    explicit = as_id(task.get("assignee_id"))
    if explicit is not None:
        return explicit if explicit in allowed else None
    return _match_owner(task.get("assignee") or "", mapping)


# ------------------------------------------------------------------- work logs
def log_entries(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every recorded work session for a task, oldest first.

    Legacy tasks only ever stored a single `started_at`/`ended_at` pair, so that
    is presented as a one-element list rather than being ignored.
    """
    time_log = task.get("time_log") or {}
    entries = time_log.get("entries")
    if isinstance(entries, list) and entries:
        return entries
    if time_log.get("started_at"):
        return [
            {
                "user_id": time_log.get("user_id"),
                "started_at": time_log.get("started_at"),
                "ended_at": time_log.get("ended_at"),
            }
        ]
    return []


def entry_seconds(entry: Dict[str, Any]) -> int:
    """Whole seconds a single work session ran for (0 when still open/invalid)."""
    started, ended = entry.get("started_at"), entry.get("ended_at")
    if not started or not ended:
        return 0
    try:
        delta = datetime.fromisoformat(str(ended)) - datetime.fromisoformat(str(started))
    except (TypeError, ValueError):
        return 0
    return max(0, int(delta.total_seconds()))


def task_seconds(task: Dict[str, Any]) -> int:
    """Total tracked seconds on a task across every session."""
    return sum(entry_seconds(entry) for entry in log_entries(task))


def open_entry(task: Dict[str, Any], user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """The session still running on a task, if any."""
    for entry in reversed(log_entries(task)):
        if entry.get("ended_at"):
            continue
        if user_id is not None and as_id(entry.get("user_id")) not in (None, user_id):
            continue
        return entry
    return None


def start_work_log(
    task: Dict[str, Any], user_id: int, moment: Optional[datetime] = None
) -> Dict[str, Any]:
    """Open a work session for `user_id` on `task`.

    Idempotent: asking to start a task that is already running returns the live
    session instead of stacking a second one.
    """
    running = open_entry(task)
    if running is not None:
        return running

    time_log = task.setdefault("time_log", {})
    entry = {
        "user_id": user_id,
        "started_at": utc_iso(moment),
        "ended_at": None,
    }
    time_log.setdefault("entries", []).append(entry)
    # Keep the legacy flat fields in step so older readers still show a time.
    time_log["started_at"] = entry["started_at"]
    time_log["ended_at"] = None
    time_log["user_id"] = user_id
    return entry


def stop_work_log(
    task: Dict[str, Any], user_id: int, moment: Optional[datetime] = None
) -> Dict[str, Any]:
    """Close the live work session on `task`, raising ValueError when none is open."""
    running = open_entry(task)
    if running is None:
        raise ValueError("This task has no work session running.")

    running["ended_at"] = utc_iso(moment)
    if as_id(running.get("user_id")) is None:
        running["user_id"] = user_id
    time_log = task.setdefault("time_log", {})
    time_log["started_at"] = running.get("started_at") or time_log.get("started_at")
    time_log["ended_at"] = running["ended_at"]
    time_log["user_id"] = running.get("user_id") or user_id
    return running


# --------------------------------------------------------------- contributions
def _blank_stats(user_id: int, name: str) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "name": name,
        "assigned": 0,
        "completed": 0,
        "logged_seconds": 0,
        "logged_hours": 0.0,
        "tasks": [],
        "work_logs": [],
    }


def _record_session(record: Dict[str, Any], task: Dict[str, Any], sprint_id: str, entry: Dict[str, Any]) -> None:
    """Attach one work session to a member and credit its duration.

    US-21: the session is recorded even when it lasted no measurable time, so the
    User ID / Task ID / timestamp association is never silently dropped; only the
    seconds credited to the member require a positive duration.
    """
    seconds = entry_seconds(entry)
    if seconds > 0:
        record["logged_seconds"] += seconds
    record["work_logs"].append(
        {
            "task_id": task.get("id"),
            "task_title": task.get("title", "Untitled task"),
            "sprint_id": sprint_id,
            "user_id": as_id(entry.get("user_id")) or record["user_id"],
            "started_at": entry.get("started_at"),
            "ended_at": entry.get("ended_at"),
            "seconds": seconds,
        }
    )


def compute_contributions(
    project: Dict[str, Any],
    users: Iterable[Dict[str, Any]],
    allowed_ids: Optional[Iterable[int]] = None,
) -> Dict[str, Any]:
    """Recount every project member's assigned tasks, completions and tracked time.

    US-20: this replaces the browser-side arithmetic. The caller persists the
    result onto the project so the numbers are identical on every device.

    US-21: completed task counts come from the same recomputation as the logged
    hours, so a burndown and a contribution table can never disagree.

    The stored figures are deliberately raw (counts and tracked time); nothing
    here derives a single combined number from them.
    """
    users = list(users or [])
    users_by_id = {
        parsed: user
        for user in users
        for parsed in [as_id(user.get("user_id"))]
        if parsed is not None
    }
    ids = list(allowed_ids) if allowed_ids is not None else member_ids(project)
    mapping = name_to_id_map(users, ids)

    stats: Dict[int, Dict[str, Any]] = {
        user_id: _blank_stats(user_id, display_name(users_by_id, user_id))
        for user_id in ids
    }

    for sprint in project.get("sprints", []) or []:
        sprint_id = str(sprint.get("id", ""))
        sprint_name = sprint.get("name", "Sprint")
        state = sprint.get("kanban_state") or {}
        for column in COLUMNS:
            for task in state.get(column, []) or []:
                owner = resolve_owner(task, ids, mapping)
                for entry in log_entries(task):
                    logged_by = as_id(entry.get("user_id")) or owner
                    owner_record = stats.get(owner)
                    # Hours are credited to whoever logged them; a session with no
                    # explicit logger falls back to the task's owner.
                    target = stats.get(logged_by) if logged_by is not None else owner_record
                    if target is not None:
                        _record_session(target, task, sprint_id, entry)

                if owner is None or owner not in stats:
                    continue
                record = stats[owner]
                record["assigned"] += 1
                if column == "completed":
                    record["completed"] += 1
                record["tasks"].append(
                    {
                        "title": task.get("title", "Untitled task"),
                        "status": column,
                        "sprint": sprint_name,
                        "sprint_id": sprint_id,
                    }
                )

    for record in stats.values():
        record["logged_hours"] = round(record["logged_seconds"] / 3600.0, 2)
        record["tasks"].sort(key=lambda item: (item["status"] != "completed", item["title"].casefold()))
        record["work_logs"].sort(key=lambda item: str(item.get("started_at") or ""))

    ranked = sorted(
        stats.values(),
        key=lambda item: (-item["assigned"], item["name"].casefold()),
    )
    return {
        "members": ranked,
        "total_logged_seconds": sum(item["logged_seconds"] for item in ranked),
    }


def find_task(project: Dict[str, Any], sprint_id: Any, task_id: Any) -> Dict[str, Any]:
    """Locate a task on a sprint's board, raising ValueError when it is missing."""
    sprint = next(
        (s for s in project.get("sprints", []) or [] if str(s.get("id")) == str(sprint_id)),
        None,
    )
    if sprint is None:
        raise ValueError("Sprint not found")

    wanted = str(task_id)
    if wanted.startswith("task-"):
        wanted = wanted[5:]
    for column in COLUMNS:
        for task in (sprint.get("kanban_state") or {}).get(column, []) or []:
            raw = str(task.get("id", ""))
            if raw == str(task_id) or raw == wanted or (raw.startswith("task-") and raw[5:] == wanted):
                return task
    raise ValueError("Task not found on this sprint")


