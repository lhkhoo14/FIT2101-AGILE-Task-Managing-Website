"""
Sprint membership and sorting helpers.

Pure Python (no pyscript imports) so it can be shared by the sprint dashboard
and the sprint page, and unit-tested outside the browser.
"""

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
DEFAULT_PRIORITY = "medium"

SORT_DATE = "date"
SORT_PRIORITY = "priority"
SORT_NAME = "name"


def is_sprint_member(sprint, user_id) -> bool:
    """True if user_id is assigned to the sprint.

    Legacy sprints saved before members existed have no "members" key and
    stay open to everyone, so old data doesn't suddenly lock people out.
    A sprint with an explicit (even empty) members list is restricted.
    """
    members = sprint.get("members")
    if members is None:
        return True
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    return uid in {int(m) for m in members}


def sprint_created_at(sprint) -> int:
    """Creation time in ms. Falls back to the id (a ms timestamp for sprints
    created by older versions of the UI), else 0 for the seeded sprints."""
    created = sprint.get("created_at")
    if created is not None:
        try:
            return int(created)
        except (TypeError, ValueError):
            return 0
    sid = str(sprint.get("id", ""))
    return int(sid) if sid.isdigit() and len(sid) >= 12 else 0


def sort_sprints(sprints, sort_key):
    """Return a new sorted list. Python's sort is stable, so ties keep their
    original (creation) order.

    date     -> newest first
    priority -> high, medium, low
    name     -> A-Z, case-insensitive
    """
    items = list(sprints)
    if sort_key == SORT_PRIORITY:
        return sorted(items, key=lambda s: PRIORITY_ORDER.get(s.get("priority"), PRIORITY_ORDER[DEFAULT_PRIORITY]))
    if sort_key == SORT_NAME:
        return sorted(items, key=lambda s: str(s.get("name", "")).casefold())
    return sorted(items, key=lambda s: -sprint_created_at(s))
