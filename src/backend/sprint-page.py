import sys
import json
import copy
import asyncio
import time
from datetime import datetime, timezone


# Ensure the current directory is in the system path for local module imports
if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar
from constants import DEFAULT_SPRINTS  # fallback only — see _load_sprints below
from sprint_access import is_sprint_member
import js  # type: ignore

from models.server_data import ServerData

# --- CURRENT USER (for checklist ownership checks) ---
server_data = ServerData()
_current_user_id = server_data.get_active_session()
current_user = server_data.find_user_by_id(int(_current_user_id)) if _current_user_id else None

# ==========================================
# CONSTANTS & GLOBAL STATE
# ==========================================
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

SPRINTS_STORAGE_KEY = "sprints_list"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"
KANBAN_STATE_KEY_PREFIX = "kanban_state_"

_sprint_id = None
_sprint_ended = False
_has_access = False  # True only once the current user is confirmed as an assigned member
FLASH_KEY = "flash_snackbar"  # shown by sprint-dashboard.html after a redirect


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

    # --- NEW CHECKLIST PROGRESS HTML ---
    done_cnt, total_cnt, pct = _checklist_progress(task)
    if total_cnt > 0:
        progress_html = f"""
        <div class="card-checklist-progress">
            <div class="card-progress-bar-bg">
                <div class="card-progress-bar-fill" style="width: {pct}%;"></div>
            </div>
            <span class="card-progress-text">{done_cnt}/{total_cnt}</span>
        </div>
        """
    else:
        progress_html = ""
    # -----------------------------------

    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{task['tag']}">{task['tag'].capitalize()}</span>
        </div>
        <p class="task-card-title">{task['title']}</p>
        {progress_html}
        <div class="task-card-footer">
            <span class="priority-badge priority-{task['priority']}">{task['priority'].capitalize()}</span>
            {avatar_html}
        </div>
    """
    
    return card


def _current_actor():
    # Resolve the signed-in user's display name for sprint-board events.
    try:
        raw = window.localStorage.getItem("pyscript_app_data")
        data = json.loads(raw) if raw else {}
        active_id = str(window.localStorage.getItem("session_user_id") or "")
        user = next(
            (item for item in data.get("users", []) if str(item.get("user_id")) == active_id),
            None,
        )
        return user.get("username") or user.get("email") if user else "Unknown user"
    except (ValueError, TypeError):
        return "Unknown user"


async def _record_change(action, sprint, task=None, from_status=None, to_status=None):
    # Persist a timestamped sprint-board event in the shared IndexedDB store.
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
    await window.sprintHistoryDb.add(js.JSON.parse(json.dumps(entry)))


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

    # Only members assigned to this sprint may open its page (this also covers
    # anyone who types the sprint_id into the URL directly).
    global _has_access
    if not is_sprint_member(sprint, current_user.user_id if current_user else None):
        window.sessionStorage.setItem(FLASH_KEY, "You are not assigned to that sprint.")
        window.location.href = "sprint-dashboard.html"
        return
    _has_access = True

    _apply_header_and_lock_state(sprint)

    state = _load_kanban_state(_sprint_id)
    state = _merge_handoff_into_backlog_column(_sprint_id, state)
    _render_board(state)


# ==========================================
# EVENT HANDLERS
# ==========================================
@when("click", "#create-sprint-btn")
def handle_create_sprint_navigation(event):
    _navigate_to_dashboard(action="create-sprint")


@when("click", "#nav-all-projects")
def handle_show_sprints(event):
    _navigate_to_dashboard(view="sprints")


@when("click", "#nav-members")
def handle_show_members(event):
    _navigate_to_dashboard(view="members")


@when("click", "#nav-history")
def handle_show_history(event):
    _navigate_to_dashboard(view="history")


@when("click", "#nav-contributions")
def handle_show_contributions(event):
    _navigate_to_dashboard(view="contributions")


@when("click", "#settings-btn")
def handle_unavailable_settings(event):
    asyncio.ensure_future(show_snackbar("Settings are not available yet."))


def _navigate_to_dashboard(view=None, action=None):
    if window.isEmbeddedSprintPage:
        payload = {"type": "sprint-dashboard-navigation", "view": view, "action": action}
        window.parent.postMessage(js.JSON.parse(json.dumps(payload)), str(window.location.origin))
        return
    if action == "create-sprint":
        window.location.href = "sprint-dashboard.html?modal=create-sprint-modal"
    else:
        window.location.href = f"sprint-dashboard.html?view={view}"


@when("app:activate-sprint-page", "body")
def handle_activate_sprint_page(event):
    _init_page()


@when("app:card-drop", "body")
async def handle_card_drop(event):
    if _sprint_ended or not _has_access:
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

    # --- INSERTED CHECK: Gate forward moves if task has unchecked items ---
    checklist = task.get("checklist", [])
    if any(not item.get("done", False) for item in checklist):
        asyncio.ensure_future(
            show_snackbar("Complete all checklist items before moving this task forward.")
        )
        return
    # ----------------------------------------------------------------------

    state[source_column] = [t for t in state[source_column] if t["id"] != card_id]
    state[target_column].append(task)
    _save_kanban_state(_sprint_id, state)

    sprint = _find_sprint(_load_sprints(), _sprint_id) or {"name": "Sprint"}
    await _record_change("moved", sprint, task, source_column.replace("_", " "), target_column.replace("_", " "))

    _render_board(state)


# --- END SPRINT: lock the board and persist status ---
@when("click", "#end-sprint-btn")
async def handle_end_sprint(event):
    # Lock the board, persist the ended state, and record the sprint event.
    global _sprint_ended
    if _sprint_ended:
        return
    _sprint_ended = True

    sprints = _load_sprints()
    sprint = _find_sprint(sprints, _sprint_id)
    if sprint:
        sprint["status"] = "ended"
        _save_sprints(sprints)
        await _record_change("ended", sprint)

    board = web.page["kanban-board"]
    if board is not None:
        board.classList.add("sprint-ended")

    end_btn = web.page["end-sprint-btn"]
    if end_btn is not None:
        end_btn.textContent = "Sprint Ended"
        end_btn.disabled = True

    asyncio.ensure_future(show_snackbar("Sprint ended. Board is now locked."))

# --- SECTION: Task Checklist & Detail Modal ---

_open_task_id = None


def _checklist_progress(task):
    checklist = task.get("checklist", [])
    total = len(checklist)
    if total == 0:
        return 0, 0, 0
    done = sum(1 for item in checklist if item.get("done", False))
    percent = round(done / total * 100)
    return done, total, percent


def _render_task_detail_modal():
    global _open_task_id
    if not _open_task_id:
        return

    kanban_state = _load_kanban_state(_sprint_id)
    task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if t.get("id") == _open_task_id:
                task = t
                break
        if task:
            break

    if not task:
        _close_task_detail_modal()
        return

    # Title
    web.page["task-detail-title"].textContent = task.get("title", "Task Details")

    # Tag & Priority Meta
    meta_container = web.page["task-detail-meta"]
    meta_container.innerHTML = ""
    tag_span = document.createElement("span")
    tag_span.className = f"task-tag tag-{task.get('tag', 'dev').lower()}"
    tag_span.textContent = task.get("tag", "DEV")
    prio_span = document.createElement("span")
    prio_span.className = f"task-priority priority-{task.get('priority', 'medium').lower()}"
    prio_span.textContent = task.get("priority", "Medium")
    meta_container.appendChild(tag_span)
    meta_container.appendChild(prio_span)

    # Progress Bar
    done, total, percent = _checklist_progress(task)
    fill_el = web.page["task-progress-fill"]
    text_el = web.page["task-progress-text"]
    if total > 0:
        fill_el.style.width = f"{percent}%"
        text_el.textContent = f"{done} of {total} done ({percent}%)"
        web.page["task-progress-container"].classList.remove("hidden")
    else:
        fill_el.style.width = "0%"
        web.page["task-progress-container"].classList.add("hidden")

    # Checklist Rows
    items_container = web.page["checklist-items"]
    items_container.innerHTML = ""
    checklist = task.get("checklist", [])

    if not checklist:
        empty_div = document.createElement("div")
        empty_div.className = "checklist-empty"
        empty_div.textContent = "No checklist items yet."
        items_container.appendChild(empty_div)
    else:
        for idx, item in enumerate(checklist):
            row = document.createElement("div")
            row.className = "checklist-row"

            checkbox = document.createElement("input")
            checkbox.type = "checkbox"
            checkbox.id = f"chk-item-{item.get('id', idx)}"
            checkbox.dataset.itemId = str(item.get("id", ""))
            checkbox.checked = item.get("done", False)
            if _sprint_ended:
                checkbox.disabled = True

            label = document.createElement("label")
            label.htmlFor = checkbox.id
            label.textContent = item.get("text", "")

            row.appendChild(checkbox)
            row.appendChild(label)

            # --- Delete button: only visible to the item's own creator ---
            is_owner = (
                current_user is not None
                and item.get("created_by") == current_user.user_id
            )
            if is_owner and not _sprint_ended:
                delete_btn = document.createElement("button")
                delete_btn.type = "button"
                delete_btn.className = "checklist-delete-btn"
                delete_btn.title = "Delete this item"
                delete_btn.dataset.itemId = str(item.get("id", ""))
                delete_btn.textContent = "×"
                row.appendChild(delete_btn)
            # ---------------------------------------------------------------

            items_container.appendChild(row)

    # Ended sprint view-only controls
    input_el = web.page["checklist-input"]
    add_btn = web.page["checklist-add-btn"]
    if _sprint_ended:
        input_el.disabled = True
        add_btn.disabled = True
    else:
        input_el.disabled = False
        add_btn.disabled = False


@when("click", "#kanban-board")
def handle_kanban_click(event):
    card = event.target.closest(".task-card")
    if not card:
        return

    task_id = card.id
    global _open_task_id
    _open_task_id = task_id

    _render_task_detail_modal()
    web.page["task-detail-modal"].classList.remove("hidden")


@when("submit", "#checklist-add-form")
def handle_add_checklist_item(event):
    event.preventDefault()
    if _sprint_ended or not _open_task_id:
        return

    input_el = web.page["checklist-input"]
    text = input_el.value.strip()
    if not text:
        return

    kanban_state = _load_kanban_state(_sprint_id)
    target_task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if t.get("id") == _open_task_id:
                target_task = t
                break
        if target_task:
            break

    if target_task:
        if "checklist" not in target_task:
            target_task["checklist"] = []

        new_item = {
            "id": str(int(time.time() * 1000)),
            "text": text,
            "done": False,
            "created_by": current_user.user_id if current_user else None,
        }
        target_task["checklist"].append(new_item)
        _save_kanban_state(_sprint_id, kanban_state)

        input_el.value = ""
        _render_task_detail_modal()
        _render_board(kanban_state)


@when("change", "#checklist-items")
def handle_checklist_toggle(event):
    if _sprint_ended or not _open_task_id:
        return

    target = event.target
    if target.tagName.lower() != "input" or target.type != "checkbox":
        return

    item_id = target.dataset.itemId
    is_checked = target.checked

    kanban_state = _load_kanban_state(_sprint_id)
    target_task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if t.get("id") == _open_task_id:
                target_task = t
                break
        if target_task:
            break

    if target_task:
        for item in target_task.get("checklist", []):
            if str(item.get("id")) == item_id:
                item["done"] = is_checked
                break
        _save_kanban_state(_sprint_id, kanban_state)
        _render_task_detail_modal()
        _render_board(kanban_state)

@when("click", "#checklist-items")
def handle_checklist_delete(event):
    if _sprint_ended or not _open_task_id:
        return

    target = event.target
    if not target.classList.contains("checklist-delete-btn"):
        return

    item_id = target.dataset.itemId

    kanban_state = _load_kanban_state(_sprint_id)
    target_task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if t.get("id") == _open_task_id:
                target_task = t
                break
        if target_task:
            break

    if not target_task:
        return

    checklist = target_task.get("checklist", [])
    item_to_delete = next((i for i in checklist if str(i.get("id")) == item_id), None)

    # Guard: only the creator may delete their own item
    if item_to_delete is None:
        return
    if current_user is None or item_to_delete.get("created_by") != current_user.user_id:
        asyncio.ensure_future(
            show_snackbar("You can only delete checklist items you created.")
        )
        return

    target_task["checklist"] = [i for i in checklist if str(i.get("id")) != item_id]
    _save_kanban_state(_sprint_id, kanban_state)
    _render_task_detail_modal()
    _render_board(kanban_state)

def _close_task_detail_modal():
    global _open_task_id
    _open_task_id = None
    web.page["task-detail-modal"].classList.add("hidden")


@when("click", "#task-detail-close-btn")
def handle_close_modal_click(event):
    _close_task_detail_modal()


@when("click", "#task-detail-modal")
def handle_modal_backdrop_click(event):
    if event.target.id == event.currentTarget.id:
        _close_task_detail_modal()

_page_params = js.URLSearchParams.new(window.location.search)
if _page_params.get("prewarm") == "1":
    ready_message = {
        "type": "sprint-page-ready",
        "sprintId": _get_sprint_id_from_url(),
    }
    window.parent.postMessage(
        js.JSON.parse(json.dumps(ready_message)),
        str(window.location.origin),
    )
else:
    _init_page()