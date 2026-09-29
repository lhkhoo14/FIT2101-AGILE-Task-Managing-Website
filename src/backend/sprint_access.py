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

MAX_TAGS = 10
MAX_TAG_LENGTH = 20


def normalize_tags(raw) -> list:
    """Turn user input ("Frontend, #API ,, urgent") into a clean tag list.

    Accepts a comma-separated string or a list. Tags are lowercased, stripped of
    a leading "#", de-duplicated (order kept), capped in length and in number.
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


def filter_sprints_by_tag(sprints, query):
    """Sprints whose tags match the search text.

    The query is split on commas/whitespace (a leading "#" is ignored). Every
    term must partially match at least one of the sprint's tags, so "front"
    finds "frontend" and "api urgent" finds sprints tagged both. An empty
    query returns all sprints. Sprints with no tags never match a search.
    """
    terms = [w.lstrip("#").lower() for w in str(query or "").replace(",", " ").split()]
    terms = [w for w in terms if w]
    if not terms:
        return list(sprints)
    result = []
    for s in sprints:
        tags = [str(tag).lower() for tag in (s.get("tags") or [])]
        if tags and all(any(term in tag for tag in tags) for term in terms):
            result.append(s)
    return result
