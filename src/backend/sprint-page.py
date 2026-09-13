import sys
import json
import copy

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar
import js  # type: ignore

COLUMN_ORDER = ["backlog", "active", "review", "completed"]

SPRINTS_STORAGE_KEY = "sprints_list"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"   # handoff from dashboard's product backlog
KANBAN_STATE_KEY_PREFIX = "kanban_state_"       # this sprint's own board

# Seeds sprint "1" the first time its board is opened, so the demo isn't empty.
# Any other sprint starts with empty columns.
DEFAULT_KANBAN_STATE_SPRINT_1 = {
    "backlog": [
        {"id": "task-1", "title": "Design login page wireframe", "tag": "frontend", "priority": "medium", "assignee": "Chee Wei"},
        {"id": "task-2", "title": "Set up Oracle DB schema", "tag": "backend", "priority": "high", "assignee": "Ken Yit"},
    ],
    "active": [
        {"id": "task-3", "title": "Build kanban board UI", "tag": "frontend", "priority": "high", "assignee": "Wei Ho"},
    ],
    "review": [
        {"id": "task-4", "title": "Login form validation logic", "tag": "backend", "priority": "medium", "assignee": "Chee Wei"},
    ],
    "completed": [
        {"id": "task-5", "title": "Set up PyScript project", "tag": "backend", "priority": "low", "assignee": "Lip Hong"},
        {"id": "task-6", "title": "Create ServerData class", "tag": "backend", "priority": "medium", "assignee": "Chee Wei"},
    ],
}

_sprint_id = None
_sprint_ended = False


# --- URL ---
def _get_sprint_id_from_url():
    params = js.URLSearchParams.new(window.location.search)
    sid = params.get("sprint_id")
    return sid if sid else None


# --- sprints_list helpers (shared shape with dashboard) ---
def _load_sprints():
    raw = window.localStorage.getItem(SPRINTS_STORAGE_KEY)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except ValueError:
        return []


def _save_sprints(sprints):
    window.localStorage.setItem(SPRINTS_STORAGE_KEY, json.dumps(sprints))


def _find_sprint(sprints, sprint_id):
    return next((s for s in sprints if s["id"] == sprint_id), None)


# --- kanban_state helpers ---
def _load_kanban_state(sprint_id):
    raw = window.localStorage.getItem(f"{KANBAN_STATE_KEY_PREFIX}{sprint_id}")
    if not raw:
        if sprint_id == "1":
            return copy.deepcopy(DEFAULT_KANBAN_STATE_SPRINT_1)
        return {col: [] for col in COLUMN_ORDER}
    try:
        state = json.loads(raw)
    except ValueError:
        state = {col: [] for col in COLUMN_ORDER}
    for col in COLUMN_ORDER:
        state.setdefault(col, [])
    return state


def _save_kanban_state(sprint_id, state):
    window.localStorage.setItem(f"{KANBAN_STATE_KEY_PREFIX}{sprint_id}", json.dumps(state))


# --- absorb items dropped onto this sprint's card from the dashboard ---
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


# --- rendering ---
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


# --- page bootstrap ---
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


# --- DRAG START --- bound to the stable #kanban-board container, not .task-card,
# since _render_board() destroys/recreates card nodes on every load/move.
@when("dragstart", "#kanban-board")
def handle_drag_start(event):
    if _sprint_ended:
        event.preventDefault()
        return
    card = event.target.closest(".task-card")
    if not card:
        return
    event.dataTransfer.setData("text/plain", card.id)
    event.dataTransfer.effectAllowed = "move"
    card.classList.add("dragging")


@when("dragend", "#kanban-board")
def handle_drag_end(event):
    card = event.target.closest(".task-card")
    if card:
        card.classList.remove("dragging")


@when("dragover", "#kanban-board")
def handle_drag_over(event):
    if _sprint_ended:
        return
    body = event.target.closest(".kanban-column-body")
    if not body:
        return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    body.classList.add("drag-over")


@when("dragleave", "#kanban-board")
def handle_drag_leave(event):
    body = event.target.closest(".kanban-column-body")
    if body:
        body.classList.remove("drag-over")


@when("drop", "#kanban-board")
async def handle_drop(event):
    event.preventDefault()
    target_body = event.target.closest(".kanban-column-body")
    if not target_body:
        return
    target_body.classList.remove("drag-over")

    if _sprint_ended:
        return

    card_id = event.dataTransfer.getData("text/plain")
    card = web.page[card_id]
    if not card:
        return

    source_column = card.getAttribute("data-column")
    target_column = target_body.getAttribute("data-column")

    if source_column == target_column:
        return

    if _column_index(target_column) < _column_index(source_column):
        await show_snackbar("Tasks can only be pushed forward on the board.")
        return

    # Persist the move, not just the DOM change.
    state = _load_kanban_state(_sprint_id)
    task = next((t for t in state[source_column] if t["id"] == card_id), None)
    if task is None:
        return

    state[source_column] = [t for t in state[source_column] if t["id"] != card_id]
    state[target_column].append(task)
    _save_kanban_state(_sprint_id, state)

    target_body.appendChild(card)
    card.setAttribute("data-column", target_column)

    _update_column_count(source_column)
    _update_column_count(target_column)


@when("click", "#end-sprint-btn")
async def handle_end_sprint(event):
    global _sprint_ended
    _sprint_ended = True

    sprints = _load_sprints()
    sprint = _find_sprint(sprints, _sprint_id)
    if sprint:
        sprint["status"] = "ended"
        _save_sprints(sprints)  # so the dashboard's status badge reflects it too

    board = web.page["kanban-board"]
    if board is not None:
        board.classList.add("sprint-ended")

    end_btn = web.page["end-sprint-btn"]
    if end_btn is not None:
        end_btn.textContent = "Sprint Ended"
        end_btn.disabled = True

    await show_snackbar("Sprint ended. Board is now locked.")


_init_page()