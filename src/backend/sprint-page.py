import sys
import asyncio

# Ensure the current directory is in the system path for local module imports
if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore
from auth import show_snackbar
from constants import DEFAULT_SPRINTS  # fallback only — see _load_sprints below
import js  # type: ignore

from server_data import ServerData
import topbar

# ==========================================
# CONSTANTS & GLOBAL STATE
# ==========================================
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

SPRINTS_STORAGE_KEY = "sprints_list"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"
KANBAN_STATE_KEY_PREFIX = "kanban_state_"

_sprint_id = None
_project_id = None
_sprint_ended = False
_db = ServerData()

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

# ==========================================
# RENDERING & UI HELPERS
# ==========================================
def _make_task_card(task, column_key):
    card = document.createElement("div")
    card.className = "task-card"
    card.id = f"task-{task.get('id', task.get('backlog_id', ''))}"
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

    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{tag}">{tag.capitalize()}</span>
        </div>
        <p class="task-card-title">{title}</p>
        <div class="task-card-footer">
            <span class="priority-badge priority-{priority}">{priority.capitalize()}</span>
            {avatar_html}
        </div>
    """
    return card

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

    if _sprint_ended:
        board = web.page["kanban-board"]
        if board is not None:
            board.classList.add("sprint-ended")
        end_btn = web.page["end-sprint-btn"]
        if end_btn is not None:
            end_btn.textContent = "Sprint Ended"
            end_btn.disabled = True

async def _init_page():
    global _sprint_id, _project_id
    _sprint_id, _project_id = _get_url_params()

    if not _sprint_id or not _project_id:
        window.location.href = "dashboard.html"
        return

    # Fetch active sprint details from server
    sprints = await _db.get_sprints(_project_id)
    str_sprint_id = str(_sprint_id)
    sprint = next(
        (
            s for s in sprints 
            if s.get("id") == str_sprint_id 
            or s.get("sprint_id") == str_sprint_id
        ), 
        None
    )
    
    if not sprint:
        window.location.href = f"sprint-dashboard.html?project_id={_project_id}"
        return

    _apply_header_and_lock_state(sprint)

    # Fetch sprint backlog items from server database
    sprint_items = await _db.get_sprint_backlog(_project_id, _sprint_id)

    # Map backlog items into state columns
    state = {col: [] for col in COLUMN_ORDER}
    for item in sprint_items:
        status_col = item.get("status", "backlog")
        if status_col not in state:
            status_col = "backlog"
        state[status_col].append(item)

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

    if not _project_id or not _sprint_id:
        return

    sprint_items = await _db.get_sprint_backlog(_project_id, _sprint_id)
    
    # Extract clean target ID
    raw_id = card_id.replace("task-", "")
    task = next((t for t in sprint_items if str(t.get("id", t.get("backlog_id", ""))).replace("task-", "") == raw_id), None)

    if not task:
        return

    source_column = task.get("status", "backlog")
    if source_column == target_column:
        return

    # Enforce workflow rule: tasks can only be moved forward
    if _column_index(target_column) < _column_index(source_column):
        await show_snackbar("Tasks can only be pushed forward on the board.")
        return

    # Update state locally
    task["status"] = target_column
    
    state = {col: [] for col in COLUMN_ORDER}
    for item in sprint_items:
        status_col = item.get("status", "backlog")
        if status_col not in state:
            status_col = "backlog"
        
        # Prepare clean dict for backend storage
        clean_item = dict(item)
        clean_item.pop("status", None)
        state[status_col].append(clean_item)

    _render_board(state)

    # Persist move to database
    success, err_msg = await _db.update_kanban_state(_project_id, _sprint_id, state)
    if not success:
        await show_snackbar(f"Failed to update board: {err_msg}")

# --- END SPRINT: lock the board and persist status via ServerData ---
@when("click", "#end-sprint-btn")
async def handle_end_sprint(event):
    global _sprint_ended
    _sprint_ended = True

    board = web.page["kanban-board"]
    if board is not None:
        board.classList.add("sprint-ended")

    end_btn = web.page["end-sprint-btn"]
    if end_btn is not None:
        end_btn.textContent = "Sprint Ended"
        end_btn.disabled = True

    await show_snackbar("Sprint ended. Board is now locked.")

@when("click", "#toggle-sidebar-btn")
def toggle_sidebar(event):
    # Retrieve either project-sidebar or standard dashboard sidebar
    sidebar = web.page["#project-sidebar"] or web.page["#sidebar"]
    if sidebar:
        if "collapsed" in sidebar.classes:
            sidebar.classes.remove("collapsed")
        else:
            sidebar.classes.add("collapsed")

@when("click", "#back-to-project-btn")
def return_to_project(event):
    """Returns the user to the sprint dashboard."""
    window.location.href = f"sprint-dashboard.html?project_id={_project_id}"

# Launch async page initialization
asyncio.ensure_future(_init_page())