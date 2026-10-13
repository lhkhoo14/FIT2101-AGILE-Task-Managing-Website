import sys
import asyncio
import json
import time
from datetime import datetime, timezone


# Ensure the current directory is in the system path for local module imports
if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar # type: ignore
from sprint_access import is_sprint_member # type: ignore
from html import escape
import charts
import js  # type: ignore

from server_data import ServerData
import topbar # type: ignore

# ServerData owns the FastAPI session and provides the sprint/project API.
# The page keeps only the currently displayed board in memory; every mutation
# is persisted with update_kanban_state on the server.
server_data = ServerData()
_current_user_id = server_data.get_active_session()

# --- TEMP DEMO ROLE (stand-in until the user model has a real role field) ---
_DEMO_ROLE_KEY = "demo_role"


def _get_current_role():
    role = window.localStorage.getItem(_DEMO_ROLE_KEY)
    return role if role in ("manager", "employee") else "employee"


def _is_manager():
    return _get_current_role() == "manager"

# ==========================================
# CONSTANTS & GLOBAL STATE
# ==========================================
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

# CHANGE: tasks may move backlog -> active with checklist items still open, but
# every column after this one requires a fully completed checklist. Editing this
# value moves the gate (e.g. "backlog" gates every forward move).
CHECKLIST_GATE_COLUMN = "active"

_sprint_id = None
_project_id = None
_sprint_ended = False
_has_access = False
_active_sprint = None
_kanban_state = {}
_assignees = []          # [(user_id, display name)] who can be assigned tasks in this sprint
_watcher_started = False
_search_query = ""

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
    if not _project_id or not _sprint_id:
        return
    success, err = await server_data.update_kanban_state(_project_id, _sprint_id, state)
    if not success:
        await show_snackbar(f"Failed to update board: {err}")
    return success


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

    # --- TIME LOG BADGE HTML ---
    _, _, time_status, _ = _time_log_summary(task)
    if time_status:
        time_html = f'<div class="card-time-log">⏱ {escape(time_status)}</div>'
    else:
        time_html = ""
    # ---------------------------

    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{tag}">{tag.capitalize()}</span>
        </div>
        <p class="task-card-title">{escape(str(task['title']))}</p>
        {dates_html}
        {progress_html}
        {time_html}
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
    # US-20: the activity feed is stored on the server, so an event recorded here
    # is visible on every device that opens this project.
    if not _project_id:
        return
    actor = await _current_actor()
    if action == "moved":
        target = task.get("title", "a task") if task else "a task"
        message = (
            f"{actor} moved {target} from {from_status} to {to_status} "
            f"in {sprint.get('name', 'a sprint')}"
        )
    else:
        message = f"{actor} ended {sprint.get('name', 'a sprint')}"

    success, err = await server_data.record_change(
        _project_id,
        message,
        action=action,
        sprint_id=_sprint_id,
        sprint_name=sprint.get("name", "Sprint"),
        task_id=task.get("id") if task else None,
        task_title=task.get("title") if task else None,
        from_status=from_status,
        to_status=to_status,
    )
    if not success:
        print(f"[Change History] {err}")


def _task_matches_search(task, query):
    if not query:
        return True
    query = query.lower()
    return query in str(task.get("title", "")).lower() or query in str(task.get("tag", "")).lower()


def _render_board(state):
    for column_key in COLUMN_ORDER:
        body = web.page[f"column-{column_key}"]
        if body:
            body.innerHTML = ""
            for task in state.get(column_key, []):
                if _task_matches_search(task, _search_query):
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

    role_select = web.page["demo-role-select"]
    if role_select is not None:
        role_select.value = _get_current_role()

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

    if not _is_manager():
        # Employees: forward-only, and cannot self-move into Completed
        if _column_index(target_column) < _column_index(source_column):
            await show_snackbar("Tasks can only be pushed forward on the board.")
            return

        if target_column == "completed":
            await show_snackbar("Only a manager can move a task to Completed.")
            return

        # CHANGE: only moves PAST the gate column need a finished checklist, so a
        # task can be picked up and started while work is still outstanding.
        if _column_index(target_column) > _column_index(CHECKLIST_GATE_COLUMN):
            checklist = task.get("checklist", [])
            if any(not item.get("done", False) for item in checklist):
                await show_snackbar(
                    f"Complete all checklist items before moving this task to {target_column}."
                )
                return
    # Managers may otherwise move tasks in any direction, to any column...

    # ...but NOBODY (manager included) may complete a task with unchecked checklist items.
    if target_column == "completed":
        pending = _unchecked_count(task)
        if pending:
            noun = "item" if pending == 1 else "items"
            await show_snackbar(
                f"Tick off all checklist items first ({pending} {noun} remaining) "
                "before moving this task to Completed."
            )
            return

    source_index = state[source_column].index(task)
    state[source_column].remove(task)
    task.pop("status", None)
    state[target_column].append(task)

    sprint = _active_sprint or {"name": "Sprint"}
    if not await _persist_kanban_state(state):
        # Server refused the move: put the card back so the board matches the server.
        state[target_column].remove(task)
        state[source_column].insert(source_index, task)
        _render_board(state)
        return
    await _record_change("moved", sprint, task, source_column.replace("_", " "), target_column.replace("_", " "))

    _render_board(state)

# --- END SPRINT: lock the board and persist status via ServerData ---
@when("click", "#end-sprint-btn")
async def handle_end_sprint(event):
    # Lock the board, persist the ended state, and record the sprint event.
    global _sprint_ended, _active_sprint
    if _sprint_ended:
        return
    if not _project_id or not _sprint_id:
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

# --- Search Bar
@when("input", "#global-search")
def handle_search_input(event):
    global _search_query
    _search_query = event.target.value.strip()
    _render_board(_kanban_state)

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


def _unchecked_count(task):
    return sum(1 for item in task.get("checklist", []) if not item.get("done", False))


def _find_task_and_column(task_id):
    """Return (task, column_key) for a card id, or (None, None)."""
    wanted = _normalized_task_id(task_id)
    for column_key, column_tasks in _kanban_state.items():
        for t in column_tasks:
            if _normalized_task_id(t.get("id")) == wanted:
                return t, column_key
    return None, None


def _render_task_detail_modal():
    global _open_task_id
    if not _open_task_id:
        return

    kanban_state = _kanban_state
    task = None
    task_column = None
    for col_key, col_tasks in kanban_state.items():
        for t in col_tasks:
            if _normalized_task_id(t.get("id")) == _normalized_task_id(_open_task_id):
                task = t
                task_column = col_key
                break
        if task:
            break

    if not task:
        _close_task_detail_modal()
        return

    is_manager = _is_manager()

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
            # Ended sprint = read only. A completed task keeps its ticks (un-ticking would
            # leave a "completed" task with unfinished work).
            if _sprint_ended or (task_column == "completed" and item.get("done", False)):
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
    if _sprint_ended or task_column == "completed":
        input_el.disabled = True
        add_btn.disabled = True
        input_el.placeholder = (
            "Move the task out of Completed to add items"
            if task_column == "completed" and not _sprint_ended
            else "Add a sub-item..."
        )
    else:
        input_el.disabled = False
        add_btn.disabled = False
        input_el.placeholder = "Add a sub-item..."

    # --- Manager Feedback (Review tab only) ---
    feedback_section = web.page["review-feedback-section"]
    if task_column == "review":
        feedback_section.classList.remove("hidden")

        messages_el = web.page["feedback-messages"]
        messages_el.innerHTML = ""
        feedback_list = task.get("feedback") or []
        if not feedback_list:
            empty_div = document.createElement("div")
            empty_div.className = "feedback-empty"
            empty_div.textContent = "No feedback yet."
            messages_el.appendChild(empty_div)
        else:
            for msg in feedback_list:
                msg_div = document.createElement("div")
                msg_div.className = "feedback-message"

                text_span = document.createElement("span")
                author_span = document.createElement("span")
                author_span.className = "feedback-author"
                author_span.textContent = f"{msg.get('author', 'Manager')}:"
                text_span.appendChild(author_span)
                text_span.appendChild(document.createTextNode(f" {msg.get('text', '')}"))
                msg_div.appendChild(text_span)

                # Only the manager who posted it can delete their own feedback
                is_own_feedback = (
                    is_manager
                    and _current_user_id is not None
                    and msg.get("author_id") == _current_user_id
                )
                if is_own_feedback and not _sprint_ended:
                    delete_btn = document.createElement("button")
                    delete_btn.type = "button"
                    delete_btn.className = "feedback-delete-btn"
                    delete_btn.title = "Delete this feedback"
                    delete_btn.dataset.feedbackId = str(msg.get("id", ""))
                    delete_btn.textContent = "×"
                    msg_div.appendChild(delete_btn)

                messages_el.appendChild(msg_div)

        feedback_input = web.page["feedback-input"]
        feedback_btn = web.page["feedback-add-btn"]
        can_post = is_manager and not _sprint_ended
        feedback_input.disabled = not can_post
        feedback_btn.disabled = not can_post
    else:
        feedback_section.classList.add("hidden")

    # --- Time Log UI ---
    started_fmt, ended_fmt, duration_str, status_txt = _time_log_summary(task)
    start_btn = web.page["start-task-btn"]
    end_btn = web.page["end-task-btn"]
    status_el = web.page["time-log-status"]

    time_log = task.get("time_log") or {}
    has_started = bool(time_log.get("started_at"))
    has_ended = bool(time_log.get("ended_at"))

    if _sprint_ended:
        start_btn.disabled = True
        end_btn.disabled = True
    else:
        start_btn.disabled = has_started
        end_btn.disabled = (not has_started) or has_ended

    status_el.innerHTML = ""
    if not has_started:
        status_el.textContent = "Not started yet."
    else:
        lines = [f"Started: {started_fmt}"]
        if has_ended:
            lines.append(f"Ended: {ended_fmt}")
            lines.append(f"Duration: {duration_str}")
        for line in lines:
            line_div = document.createElement("div")
            line_div.textContent = line
            status_el.appendChild(line_div)


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
        if not s_start or not s_end:
            return
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

    if not _project_id or not _sprint_id:
        return
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

    target_task, task_column = _find_task_and_column(_open_task_id)
    if not target_task:
        return

    if task_column == "completed":
        # A new (unticked) item would leave a "completed" task with unfinished work.
        await show_snackbar("Move this task out of Completed before adding checklist items.")
        return

    new_item = {
        "id": str(int(time.time() * 1000)),
        "text": text,
        "done": False,
        "created_by": _current_user_id,
    }
    target_task.setdefault("checklist", []).append(new_item)

    if not await _persist_kanban_state(_kanban_state):
        target_task["checklist"].remove(new_item)  # keep the UI in sync with the server
        _render_task_detail_modal()
        return

    input_el.value = ""
    _render_task_detail_modal()
    _render_board(_kanban_state)


@when("change", "#checklist-items")
async def handle_checklist_toggle(event):
    if _sprint_ended or not _open_task_id:
        return

    target = event.target
    if target.tagName.lower() != "input" or target.type != "checkbox":
        return

    item_id = target.dataset.itemId
    is_checked = target.checked

    target_task, task_column = _find_task_and_column(_open_task_id)
    if not target_task:
        return

    item = next((i for i in target_task.get("checklist", []) if str(i.get("id")) == item_id), None)
    if item is None:
        return

    if task_column == "completed" and not is_checked:
        # Completed tasks must keep every item ticked.
        await show_snackbar("Move this task out of Completed before un-ticking checklist items.")
        _render_task_detail_modal()
        return

    previous = item.get("done", False)
    item["done"] = is_checked

    if not await _persist_kanban_state(_kanban_state):
        item["done"] = previous  # the save failed, so un-tick/re-tick the box to match the server
        _render_task_detail_modal()
        return

    _render_task_detail_modal()
    _render_board(_kanban_state)

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

@when("submit", "#feedback-add-form")
async def handle_add_feedback(event):
    event.preventDefault()
    if _sprint_ended or not _open_task_id or not _is_manager():
        return

    input_el = web.page["feedback-input"]
    text = input_el.value.strip()
    if not text:
        return

    target_task = _find_open_task()
    if target_task is None:
        return

    if not target_task.get("feedback"):
        target_task["feedback"] = []

    target_task["feedback"].append({
        "id": str(int(time.time() * 1000)),
        "text": text,
        "author": await _current_actor(),
        "author_id": _current_user_id,
    })
    await _persist_kanban_state(_kanban_state)

    input_el.value = ""
    _render_task_detail_modal()


@when("click", "#feedback-messages")
async def handle_delete_feedback(event):
    if _sprint_ended or not _open_task_id or not _is_manager():
        return

    target = event.target
    if not target.classList.contains("feedback-delete-btn"):
        return

    feedback_id = target.dataset.feedbackId

    target_task = _find_open_task()
    if target_task is None:
        return

    feedback_list = target_task.get("feedback") or []
    msg_to_delete = next((m for m in feedback_list if str(m.get("id")) == feedback_id), None)

    # Guard: only the manager who posted it may delete it
    if msg_to_delete is None:
        return
    if _current_user_id is None or msg_to_delete.get("author_id") != _current_user_id:
        asyncio.ensure_future(
            show_snackbar("You can only delete feedback you posted.")
        )
        return

    target_task["feedback"] = [m for m in feedback_list if str(m.get("id")) != feedback_id]
    await _persist_kanban_state(_kanban_state)
    _render_task_detail_modal()


@when("change", "#demo-role-select")
def handle_role_change(event):
    window.localStorage.setItem(_DEMO_ROLE_KEY, event.target.value)
    _render_board(_kanban_state)
    if _open_task_id:
        _render_task_detail_modal()


# --- SECTION: Task Time Logging ---

def _parse_stamp(value):
    """ISO stamp -> datetime, or None when it is missing/unreadable.

    US-21: work sessions are stamped by the server in UTC, while tasks logged
    before the switchover carry a naive local stamp. Treating a naive stamp as
    UTC keeps the two comparable instead of raising on the subtraction, and
    converting to the browser's timezone keeps the display local.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _time_log_summary(task):
    """(started, ended, duration, status) for a task's tracked work.

    US-21: the server stores each work session separately, so the duration is the
    sum of every finished session rather than only the most recent one. Tasks that
    predate session tracking carry a single flat started_at/ended_at pair and are
    read as one session.
    """
    time_log = task.get("time_log")
    if not time_log:
        return "", "", "", ""

    entries = [entry for entry in (time_log.get("entries") or []) if isinstance(entry, dict)]
    if not entries:
        entries = [
            {"started_at": time_log.get("started_at"), "ended_at": time_log.get("ended_at")}
        ]

    started_fmt = ""
    ended_fmt = ""
    duration_str = ""
    status_txt = ""
    total_seconds = 0
    running = False

    for entry in entries:
        start = _parse_stamp(entry.get("started_at"))
        end = _parse_stamp(entry.get("ended_at"))
        if start is not None and not started_fmt:
            started_fmt = start.strftime("%b %d, %Y %I:%M %p")
        if end is not None:
            ended_fmt = end.strftime("%b %d, %Y %I:%M %p")
        if start is None:
            continue
        if end is None:
            running = True
            continue
        total_seconds += max(0, int((end - start).total_seconds()))

    if started_fmt:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        if running:
            status_txt = "In progress"
        elif ended_fmt:
            status_txt = duration_str

    return started_fmt, ended_fmt, duration_str, status_txt


async def _submit_time_log(action, verb):
    """US-21: open or close the work session on the currently open task.

    The server owns the clock and stamps the session with the acting User ID and
    the Task ID, then returns the task's updated time_log. That record is copied
    onto the in-memory board so the card badge and the dialog match what is
    stored, and the contribution totals are recalculated server-side in the same
    transaction.
    """
    if _sprint_ended or not _open_task_id:
        return

    target_task = _find_open_task()
    if target_task is None:
        return

    if not _project_id or not _sprint_id:
        return
    success, err, payload = await server_data.log_task_time(
        _project_id, _sprint_id, target_task.get("id"), action
    )
    if not success or not payload:
        await show_snackbar(f"Could not {verb} the timer: {err}")
        return

    target_task["time_log"] = payload.get("time_log") or target_task.get("time_log")
    _render_task_detail_modal()
    _render_board(_kanban_state)


@when("click", "#start-task-btn")
async def handle_start_task(event):
    await _submit_time_log("start", "start")


@when("click", "#end-task-btn")
async def handle_end_task(event):
    await _submit_time_log("stop", "stop")


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
