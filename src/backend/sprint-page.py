import sys
import json
import copy
import asyncio
from datetime import datetime, timezone


# Ensure the current directory is in the system path for local module imports
if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar
from constants import DEFAULT_SPRINTS  # fallback only — see _load_sprints below
import js  # type: ignore

# ==========================================
# CONSTANTS & GLOBAL STATE
# ==========================================
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

SPRINTS_STORAGE_KEY = "sprints_list"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"
KANBAN_STATE_KEY_PREFIX = "kanban_state_"
CHANGE_HISTORY_KEY = "sprint_change_history"

_sprint_id = None
_sprint_ended = False


# ==========================================
# URL HELPERS
# ==========================================

def _get_sprint_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    sid = params.get("sprint_id")
    return sid if sid else None


# ==========================================
# SPRINT STORAGE HELPERS
# ==========================================
def _load_sprints():
    raw = window.localStorage.getItem(SPRINTS_STORAGE_KEY)
    if not raw:
        # Belt-and-suspenders: only matters if someone opens sprint-page.html
        # directly via URL before ever visiting the dashboard. Doesn't save —
        # the dashboard owns seeding sprints_list into localStorage.
        return list(DEFAULT_SPRINTS)
    try:
        return json.loads(raw)
    except ValueError:
        return list(DEFAULT_SPRINTS)


def _save_sprints(sprints):
    window.localStorage.setItem(SPRINTS_STORAGE_KEY, json.dumps(sprints))


def _find_sprint(sprints, sprint_id):
    return next((s for s in sprints if s["id"] == sprint_id), None)

# ==========================================
# KANBAN BOARD STATE HELPERS
# ==========================================

def _load_kanban_state(sprint_id):
    from constants import DEFAULT_KANBAN_STATES  # local import keeps top-level imports lean

    raw = window.localStorage.getItem(f"{KANBAN_STATE_KEY_PREFIX}{sprint_id}")
    if not raw:
        seed = DEFAULT_KANBAN_STATES.get(sprint_id)
        if seed is not None:
            state = copy.deepcopy(seed)
        else:
            state = {col: [] for col in COLUMN_ORDER}
        _save_kanban_state(sprint_id, state)  # persist so this sprint's data is stable going forward
        return state
    try:
        state = json.loads(raw)
    except ValueError:
        state = {col: [] for col in COLUMN_ORDER}
    for col in COLUMN_ORDER:
        state.setdefault(col, [])
    return state


def _save_kanban_state(sprint_id, state):
    window.localStorage.setItem(f"{KANBAN_STATE_KEY_PREFIX}{sprint_id}", json.dumps(state))


def _current_actor():
    try:
        raw = window.localStorage.getItem("pyscript_app_data")
        data = json.loads(raw) if raw else {}
        active_id = str(window.localStorage.getItem("session_user_id") or "")
        user = next(
            (user for user in data.get("users", []) if str(user.get("user_id")) == active_id),
            None,
        )
        return user.get("username") or user.get("email") if user else "Unknown user"
    except (ValueError, TypeError):
        return "Unknown user"


def _record_change(action, sprint, task=None, from_status=None, to_status=None):
    raw = window.localStorage.getItem(CHANGE_HISTORY_KEY)
    try:
        history = json.loads(raw) if raw else []
    except (ValueError, TypeError):
        history = []

    entry = {
        "action": action,
        "message": (
            f"{_current_actor()} moved {task.get('title', 'a task')} from "
            f"{from_status} to {to_status} in {sprint.get('name', 'a sprint')}"
            if action == "moved"
            else f"{_current_actor()} ended {sprint.get('name', 'a sprint')}"
        ),
        "sprint_id": _sprint_id,
        "sprint_name": sprint.get("name", "Sprint"),
        "task_id": task.get("id") if task else None,
        "task_title": task.get("title") if task else None,
        "from_status": from_status,
        "to_status": to_status,
        "actor": _current_actor(),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    history.append(entry)
    window.localStorage.setItem(CHANGE_HISTORY_KEY, json.dumps(history[-500:]))


# ==========================================
# BACKLOG HANDOFF HELPERS
# ==========================================

def _load_backlog_handoff(sprint_id):
    raw = window.localStorage.getItem(f"{SPRINT_BACKLOG_KEY_PREFIX}{sprint_id}")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except ValueError:
        return []


def _clear_backlog_handoff(sprint_id):
    window.localStorage.setItem(f"{SPRINT_BACKLOG_KEY_PREFIX}{sprint_id}", json.dumps([]))


def _merge_handoff_into_backlog_column(sprint_id, state):
    handoff = _load_backlog_handoff(sprint_id)
    if not handoff:
        return state
    for item in handoff:
        state["backlog"].append({
            "id": f"task-{item['id']}",
            "title": item["title"],
            "tag": item["tag"],
            "priority": item["priority"],
            "assignee": None,
        })
    _clear_backlog_handoff(sprint_id)
    _save_kanban_state(sprint_id, state)
    return state


# ==========================================
# RENDERING & UI HELPERS
# ==========================================
def _make_task_card(task, column_key):
    card = document.createElement("div")
    card.className = "task-card"
    card.id = task["id"]
    card.setAttribute("draggable", "true")
    card.setAttribute("data-column", column_key)

    assignee = task.get("assignee")
    if assignee:
        initials = "".join(part[0] for part in assignee.split()[:2]).upper()
        avatar_html = f'<div class="assignee-avatar" title="{assignee}">{initials}</div>'
    else:
        avatar_html = '<div class="assignee-avatar" title="Unassigned">?</div>'

    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{task['tag']}">{task['tag'].capitalize()}</span>
        </div>
        <p class="task-card-title">{task['title']}</p>
        <div class="task-card-footer">
            <span class="priority-badge priority-{task['priority']}">{task['priority'].capitalize()}</span>
            {avatar_html}
        </div>
    """
    return card


def _render_board(state):
    for column_key in COLUMN_ORDER:
        body = web.page[f"column-{column_key}"]
        body.innerHTML = ""
        for task in state[column_key]:
            body.appendChild(_make_task_card(task, column_key))
    _refresh_all_counts()


def _update_column_count(column_key):
    body = web.page[f"column-{column_key}"]
    count_el = web.page[f"count-{column_key}"]
    if body is not None and count_el is not None:
        count_el.textContent = str(len(body.children))


def _refresh_all_counts():
    for key in COLUMN_ORDER:
        _update_column_count(key)


def _column_index(column_key):
    return COLUMN_ORDER.index(column_key)


# ==========================================
# PAGE INITIALIZATION & BOOTSTRAP
# ==========================================
def _apply_header_and_lock_state(sprint):
    web.page["sprint-name"].textContent = sprint["name"]

    global _sprint_ended
    _sprint_ended = sprint["status"] == "ended"

    if _sprint_ended:
        board = web.page["kanban-board"]
        if board is not None:
            board.classList.add("sprint-ended")
        end_btn = web.page["end-sprint-btn"]
        if end_btn is not None:
            end_btn.textContent = "Sprint Ended"
            end_btn.disabled = True


def _init_page():
    global _sprint_id
    _sprint_id = _get_sprint_id_from_url()

    if not _sprint_id:
        window.location.href = "dashboard.html"
        return

    sprints = _load_sprints()
    sprint = _find_sprint(sprints, _sprint_id)
    if not sprint:
        window.location.href = "dashboard.html"
        return

    _apply_header_and_lock_state(sprint)

    state = _load_kanban_state(_sprint_id)
    state = _merge_handoff_into_backlog_column(_sprint_id, state)
    _render_board(state)


# ==========================================
# EVENT HANDLERS
# ==========================================
@when("app:card-drop", "body")
async def handle_card_drop(event):
    if _sprint_ended:
        return

    detail = event.detail
    card_id = detail.cardId
    target_column = detail.targetColumn

    if not card_id or not target_column:
        return

    state = _load_kanban_state(_sprint_id)

    source_column = None
    task = None
    for col in COLUMN_ORDER:
        match = next((t for t in state[col] if t["id"] == card_id), None)
        if match is not None:
            source_column = col
            task = match
            break

    if task is None or source_column == target_column:
        return

    # Restrict backward movement across columns
    if _column_index(target_column) < _column_index(source_column):
        asyncio.ensure_future(
            show_snackbar("Tasks can only be pushed forward on the board.")
        )
        return

    state[source_column] = [t for t in state[source_column] if t["id"] != card_id]
    state[target_column].append(task)
    _save_kanban_state(_sprint_id, state)

    sprint = _find_sprint(_load_sprints(), _sprint_id) or {"name": "Sprint"}
    _record_change("moved", sprint, task, source_column.replace("_", " "), target_column.replace("_", " "))

    _render_board(state)


# --- END SPRINT: lock the board and persist status ---
@when("click", "#end-sprint-btn")
async def handle_end_sprint(event):
    global _sprint_ended
    if _sprint_ended:
        return
    _sprint_ended = True

    sprints = _load_sprints()
    sprint = _find_sprint(sprints, _sprint_id)
    if sprint:
        sprint["status"] = "ended"
        _save_sprints(sprints)
        _record_change("ended", sprint)

    board = web.page["kanban-board"]
    if board is not None:
        board.classList.add("sprint-ended")

    end_btn = web.page["end-sprint-btn"]
    if end_btn is not None:
        end_btn.textContent = "Sprint Ended"
        end_btn.disabled = True

    asyncio.ensure_future(show_snackbar("Sprint ended. Board is now locked."))


_init_page()