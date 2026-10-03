import sys
import asyncio
import json
import time
from datetime import datetime, timezone


# Ensure the current directory is in the system path for local module imports
if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar
from sprint_access import is_sprint_member
from html import escape
import charts
import js  # type: ignore

from server_data import ServerData
import topbar

# ServerData owns the FastAPI session and provides the sprint/project API.
# The page keeps only the currently displayed board in memory; every mutation
# is persisted with update_kanban_state on the server.
server_data = ServerData()
_current_user_id = server_data.get_active_session()

# ==========================================
# CONSTANTS & GLOBAL STATE
# ==========================================
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

_sprint_id = None
_project_id = None
_sprint_ended = False
_has_access = False
_active_sprint = None
_kanban_state = {}
_assignees = []          # [(user_id, display name)] who can be assigned tasks in this sprint
_watcher_started = False

# ==========================================
# URL HELPERS
# ==========================================

def _get_url_params():
    params = js.URLSearchParams.new(window.location.search)
    sprint_id = params.get("sprint_id")
    project_id = params.get("project_id")

    sprint_id = int(sprint_id) if sprint_id and sprint_id.isdigit() else sprint_id
    project_id = int(project_id) if project_id and project_id.isdigit() else project_id
    return sprint_id, project_id


def _find_sprint(sprints, sprint_id):
    return next(
        (sprint for sprint in sprints if str(sprint.get("id", sprint.get("sprint_id"))) == str(sprint_id)),
        None,
    )

async def _persist_kanban_state(state):
    """Persist the current in-memory board through the FastAPI client."""
    success, err = await server_data.update_kanban_state(_project_id, _sprint_id, state)
    if not success:
        await show_snackbar(f"Failed to update board: {err}")


def _normalized_task_id(task_id):
    task_id = str(task_id or "")
    return task_id[5:] if task_id.startswith("task-") else task_id

# ==========================================
# RENDERING & UI HELPERS
# ==========================================
def _make_task_card(task, column_key):
    card = document.createElement("div")
    card.className = "task-card"
    task_id = task.get("id", task.get("backlog_id", ""))
    card.id = f"task-{_normalized_task_id(task_id)}"
    card.setAttribute("draggable", "true")
    card.setAttribute("data-column", column_key)

    assignee = task.get("assignee")
    if assignee:
        initials = "".join(part[0] for part in assignee.split()[:2]).upper()
        avatar_html = f'<div class="assignee-avatar" title="{assignee}">{initials}</div>'
    else:
        avatar_html = '<div class="assignee-avatar" title="Unassigned">?</div>'

    tag = task.get("tag", "task")
    priority = task.get("priority", "medium")
    title = task.get("title", "Untitled Task")

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

    task_start, task_end = charts.parse_iso(task.get("start_date")), charts.parse_iso(task.get("end_date"))
    if task_start and task_end:
        dates_text = f"{charts.format_day(task_start)} \u2192 {charts.format_day(task_end)}"
    elif task_start:
        dates_text = f"Starts {charts.format_day(task_start)}"
    elif task_end:
        dates_text = f"Due {charts.format_day(task_end)}"
    else:
        dates_text = ""
    dates_html = f'<p class="task-card-dates">{escape(dates_text)}</p>' if dates_text else ""

    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{tag}">{tag.capitalize()}</span>
        </div>
        <p class="task-card-title">{escape(str(task['title']))}</p>
        {dates_html}
        {progress_html}
        <div class="task-card-footer">
            <span class="priority-badge priority-{priority}">{priority.capitalize()}</span>
            {avatar_html}
        </div>
    """
    
    return card


async def _current_actor():
    user_id = server_data.get_active_session()
    user = await server_data.get_user_by_id(user_id) if user_id is not None else None
    return (user.get("username") or user.get("email")) if user else "Unknown user"


async def _record_change(action, sprint, task=None, from_status=None, to_status=None):
    # The activity feed remains browser-local; the sprint board itself is API-backed.
    actor = await _current_actor()
    entry = {
        "action": action,
        "message": (
            f"{actor} moved {task.get('title', 'a task')} from "
            f"{from_status} to {to_status} in {sprint.get('name', 'a sprint')}"
            if action == "moved"
            else f"{actor} ended {sprint.get('name', 'a sprint')}"
        ),
        "sprint_id": _sprint_id,
        "sprint_name": sprint.get("name", "Sprint"),
        "task_id": task.get("id") if task else None,
        "task_title": task.get("title") if task else None,
        "from_status": from_status,
        "to_status": to_status,
        "actor": actor,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    await window.sprintHistoryDb.add(js.JSON.parse(json.dumps(entry)))


def _render_board(state):
    for column_key in COLUMN_ORDER:
        body = web.page[f"column-{column_key}"]
        if body:
            body.innerHTML = ""
            for task in state.get(column_key, []):
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
    name_el = web.page["sprint-name"]
    if name_el:
        name_el.textContent = sprint.get("name", f"Sprint {_sprint_id}")

    global _sprint_ended
    _sprint_ended = sprint.get("status") == "ended"

    range_el = web.page["sprint-range"]
    if range_el:
        start, end = charts.parse_iso(sprint.get("start_date")), charts.parse_iso(sprint.get("end_date"))
        range_el.textContent = (
            f"{charts.format_day(start)} \u2013 {charts.format_day(end, True)}" if start and end else ""
        )
        range_el.classList.toggle("hidden", not (start and end))

    if _sprint_ended:
        board = web.page["kanban-board"]
        if board is not None:
            board.classList.add("sprint-ended")
        end_btn = web.page["end-sprint-btn"]
        if end_btn is not None:
            end_btn.textContent = "Sprint Ended"
            end_btn.disabled = True
    else:
        board = web.page["kanban-board"]
        if board is not None:
            board.classList.remove("sprint-ended")
        end_btn = web.page["end-sprint-btn"]
        if end_btn is not None:
            end_btn.textContent = "End Sprint"
            end_btn.disabled = False
            _start_end_watcher()


async def _load_assignees(sprint):
    """Sprint members (or every user, for legacy open sprints) who can be assigned tasks."""
    member_ids = sprint.get("members")
    users = []
    if member_ids is None:
        users = await server_data.get_users()
    else:
        for member_id in member_ids:
            user = await server_data.get_user_by_id(int(member_id))
            if user:
                users.append(user)
    return [(u["user_id"], u.get("username") or u.get("email") or f"User {u['user_id']}") for u in users]


def _start_end_watcher():
    global _watcher_started
    if not _watcher_started:
        _watcher_started = True
        asyncio.ensure_future(_watch_for_sprint_end())


async def _watch_for_sprint_end():
    """The server completes a sprint once its end date passes; lock an open board when that happens."""
    global _active_sprint
    while True:
        await asyncio.sleep(30)
        if not _has_access or _sprint_ended or not _project_id or not _sprint_id:
            continue
        sprint = _find_sprint(await server_data.get_sprints(_project_id), _sprint_id)
        if sprint and sprint.get("status") == "ended":
            _active_sprint = sprint
            _apply_header_and_lock_state(sprint)
            if _open_task_id:
                _render_task_detail_modal()
            await show_snackbar("This sprint has reached its end date and was completed automatically.")


async def _init_page(sprint_id=None):
    """Load the selected sprint, verify membership, and render its board."""
    global _sprint_id, _sprint_ended, _has_access, _project_id, _active_sprint, _kanban_state, _assignees
    url_sprint_id, _project_id = _get_url_params()
    _sprint_id = sprint_id or url_sprint_id
    _sprint_ended = False
    _has_access = False

    if not _sprint_id or not _project_id:
        window.location.href = "dashboard.html"
        return

    sprints = await server_data.get_sprints(_project_id)
    sprint = _find_sprint(sprints, _sprint_id)
    if not sprint:
        window.location.href = f"sprint-dashboard.html?project_id={_project_id}"
        return

    # Only members assigned to this sprint may open its page (this also covers
    # anyone who types the sprint_id into the URL directly).
    if not is_sprint_member(sprint, _current_user_id):
        window.location.href = (
            f"sprint-dashboard.html?project_id={_project_id}"
            "&view=sprints&message=You%20are%20not%20assigned%20to%20that%20sprint."
        )
        return
    _has_access = True
    _active_sprint = sprint
    _assignees = await _load_assignees(sprint)

    _apply_header_and_lock_state(sprint)

    state = await server_data.get_kanban_state(_project_id, _sprint_id)
    if state is None:
        state = {column: [] for column in COLUMN_ORDER}
        await show_snackbar("Unable to load this sprint board from the server.")
    for column in COLUMN_ORDER:
        state.setdefault(column, [])
    _kanban_state = state
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


@when("click", "#nav-effort")
def handle_show_effort(event):
    _navigate_to_dashboard(view="effort")


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
    """Return to the live dashboard iframe or navigate to a standalone dashboard."""
    if window.isEmbeddedSprintPage:
        payload = {"type": "sprint-dashboard-navigation", "view": view, "action": action}
        window.parent.postMessage(js.JSON.parse(json.dumps(payload)), str(window.location.origin))
        return
    if action == "create-sprint":
        window.location.href = f"sprint-dashboard.html?project_id={_project_id}&modal=create-sprint-modal"
    else:
        window.location.href = f"sprint-dashboard.html?project_id={_project_id}&view={view}"


@when("app:activate-sprint-page", "body")
async def handle_activate_sprint_page(event):
    await _init_page(event.detail.sprintId)


@when("app:card-drop", "body")
async def handle_card_drop(event):
    if _sprint_ended or not _has_access:
        return

    detail = event.detail
    card_id = detail.cardId
    target_column = detail.targetColumn

    if not card_id or target_column not in COLUMN_ORDER:
        return

    if not _project_id or not _sprint_id:
        return

    state = _kanban_state
    raw_id = _normalized_task_id(card_id)
    task = next(
        (
            item
            for tasks in state.values()
            for item in tasks
            if _normalized_task_id(item.get("id", item.get("backlog_id", ""))) == raw_id
        ),
        None,
    )

    if not task:
        return

    source_column = next(column for column in COLUMN_ORDER if task in state[column])
    if source_column == target_column:
        return

    # Enforce workflow rule: tasks can only be moved forward
    if _column_index(target_column) < _column_index(source_column):
        await show_snackbar("Tasks can only be pushed forward on the board.")
        return

    # --- INSERTED CHECK: Gate forward moves if task has unchecked items ---
    checklist = task.get("checklist", [])
    if any(not item.get("done", False) for item in checklist):
        asyncio.ensure_future(
            show_snackbar("Complete all checklist items before moving this task forward.")
        )
        return
    # ----------------------------------------------------------------------

    state[source_column].remove(task)
    task.pop("status", None)
    state[target_column].append(task)

    sprint = _active_sprint or {"name": "Sprint"}
    await _persist_kanban_state(state)
    await _record_change("moved", sprint, task, source_column.replace("_", " "), target_column.replace("_", " "))

    _render_board(state)

# --- END SPRINT: lock the board and persist status via ServerData ---
@when("click", "#end-sprint-btn")
async def handle_end_sprint(event):
    # Lock the board, persist the ended state, and record the sprint event.
    global _sprint_ended, _active_sprint
    if _sprint_ended:
        return
    success, err, sprint = await server_data.update_sprint_status(
        _project_id, _sprint_id, "ended"
    )
    if not success:
        await show_snackbar(f"Failed to end sprint: {err}")
        return
    _sprint_ended = True
    _active_sprint = sprint or _active_sprint
    await _record_change("ended", _active_sprint or {"name": "Sprint"})

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

    kanban_state = _kanban_state
    task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if _normalized_task_id(t.get("id")) == _normalized_task_id(_open_task_id):
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
                _current_user_id is not None
                and item.get("created_by") == _current_user_id
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

    _render_task_assignee_and_dates(task)

    # Ended sprint view-only controls
    input_el = web.page["checklist-input"]
    add_btn = web.page["checklist-add-btn"]
    if _sprint_ended:
        input_el.disabled = True
        add_btn.disabled = True
    else:
        input_el.disabled = False
        add_btn.disabled = False


def _render_task_assignee_and_dates(task):
    """Fill the assignee picker and the start/end date inputs for the open task."""
    select = web.page["task-assignee-select"]
    select.innerHTML = ""
    choices = [("", "Unassigned")] + [(f"id:{uid}", name) for uid, name in _assignees]
    current_id, current_name = task.get("assignee_id"), task.get("assignee")
    selected = ""
    if current_id is not None and any(uid == current_id for uid, _ in _assignees):
        selected = f"id:{current_id}"
    elif current_name:
        match = next((uid for uid, name in _assignees if name == current_name), None)
        if match is not None:
            selected = f"id:{match}"
        else:  # a name that is not a current member (e.g. seeded data): keep it selectable
            choices.append(("legacy", current_name))
            selected = "legacy"
    for value, label in choices:
        option = document.createElement("option")
        option.value = value
        option.textContent = label
        select.appendChild(option)
    select.value = selected
    select.disabled = _sprint_ended

    start_input, end_input = web.page["task-start-input"], web.page["task-end-input"]
    hint = web.page["task-date-hint"]
    s_start = charts.parse_iso((_active_sprint or {}).get("start_date"))
    s_end = charts.parse_iso((_active_sprint or {}).get("end_date"))
    has_range = s_start is not None and s_end is not None
    if has_range:
        start_input.min = end_input.min = s_start.isoformat()
        start_input.max = end_input.max = s_end.isoformat()
        hint.textContent = f"Dates must fall within the sprint: {charts.format_day(s_start)} \u2013 {charts.format_day(s_end, True)}."
    else:
        hint.textContent = "Task dates are unavailable because this sprint was created without a date range."
    start_input.value = task.get("start_date") or ""
    end_input.value = task.get("end_date") or ""
    start_input.disabled = end_input.disabled = _sprint_ended or not has_range
    web.page["task-details-save-btn"].disabled = _sprint_ended


def _find_open_task():
    for col_tasks in _kanban_state.values():
        for t in col_tasks:
            if _normalized_task_id(t.get("id")) == _normalized_task_id(_open_task_id):
                return t
    return None


@when("click", "#task-details-save-btn")
async def handle_save_task_details(event):
    """Validate and save the open task's assignee and start/end dates."""
    if _sprint_ended or not _open_task_id:
        return
    task = _find_open_task()
    if task is None:
        return

    start_text = web.page["task-start-input"].value
    end_text = web.page["task-end-input"].value
    start, end = charts.parse_iso(start_text), charts.parse_iso(end_text)
    s_start = charts.parse_iso((_active_sprint or {}).get("start_date"))
    s_end = charts.parse_iso((_active_sprint or {}).get("end_date"))

    if start and end and end < start:
        await show_snackbar("The task end date cannot be before its start date.")
        return
    if s_start and s_end:
        for label, value in (("start", start), ("end", end)):
            if value and not (s_start <= value <= s_end):
                await show_snackbar(
                    f"The task {label} date must be within the sprint "
                    f"({charts.format_day(s_start)} \u2013 {charts.format_day(s_end, True)})."
                )
                return

    chosen = web.page["task-assignee-select"].value
    previous = {key: task.get(key) for key in ("assignee", "assignee_id", "start_date", "end_date")}
    if chosen == "":
        task["assignee"], task["assignee_id"] = None, None
    elif chosen.startswith("id:"):
        uid = int(chosen[3:])
        task["assignee_id"] = uid
        task["assignee"] = next((name for u, name in _assignees if u == uid), task.get("assignee"))
    # "legacy" keeps the existing assignee untouched
    task["start_date"] = start_text or None
    task["end_date"] = end_text or None

    success, err = await server_data.update_kanban_state(_project_id, _sprint_id, _kanban_state)
    if not success:
        task.update(previous)  # roll back the in-memory change so the UI matches the server
        await show_snackbar(f"Could not save task details: {err}")
        return

    _render_board(_kanban_state)
    _render_task_detail_modal()
    await show_snackbar("Task details saved.")


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
async def handle_add_checklist_item(event):
    event.preventDefault()
    if _sprint_ended or not _open_task_id:
        return

    input_el = web.page["checklist-input"]
    text = input_el.value.strip()
    if not text:
        return

    kanban_state = _kanban_state
    target_task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if _normalized_task_id(t.get("id")) == _normalized_task_id(_open_task_id):
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
            "created_by": _current_user_id,
        }
        target_task["checklist"].append(new_item)
        await _persist_kanban_state(kanban_state)

        input_el.value = ""
        _render_task_detail_modal()
        _render_board(kanban_state)


@when("change", "#checklist-items")
async def handle_checklist_toggle(event):
    if _sprint_ended or not _open_task_id:
        return

    target = event.target
    if target.tagName.lower() != "input" or target.type != "checkbox":
        return

    item_id = target.dataset.itemId
    is_checked = target.checked

    kanban_state = _kanban_state
    target_task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if _normalized_task_id(t.get("id")) == _normalized_task_id(_open_task_id):
                target_task = t
                break
        if target_task:
            break

    if target_task:
        for item in target_task.get("checklist", []):
            if str(item.get("id")) == item_id:
                item["done"] = is_checked
                break
        await _persist_kanban_state(kanban_state)
        _render_task_detail_modal()
        _render_board(kanban_state)

@when("click", "#checklist-items")
async def handle_checklist_delete(event):
    if _sprint_ended or not _open_task_id:
        return

    target = event.target
    if not target.classList.contains("checklist-delete-btn"):
        return

    item_id = target.dataset.itemId

    kanban_state = _kanban_state
    target_task = None
    for col_tasks in kanban_state.values():
        for t in col_tasks:
            if _normalized_task_id(t.get("id")) == _normalized_task_id(_open_task_id):
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
    if _current_user_id is None or item_to_delete.get("created_by") != _current_user_id:
        asyncio.ensure_future(
            show_snackbar("You can only delete checklist items you created.")
        )
        return

    target_task["checklist"] = [i for i in checklist if str(i.get("id")) != item_id]
    await _persist_kanban_state(kanban_state)
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
        "sprintId": _get_url_params()[0],
    }
    window.parent.postMessage(
        js.JSON.parse(json.dumps(ready_message)),
        str(window.location.origin),
    )
else:
    asyncio.ensure_future(_init_page())