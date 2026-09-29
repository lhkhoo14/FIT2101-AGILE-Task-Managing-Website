import asyncio
import json
import time
from datetime import datetime

from pyscript import when, web, window, document  # type: ignore[reportMissingImports]
from constants import DEFAULT_SPRINTS, DEFAULT_BACKLOG_ITEMS, DEFAULT_KANBAN_STATES
import js  # type: ignore[reportMissingImports]

BACKLOG_STORAGE_KEY = "product_backlog_items"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"
SPRINTS_STORAGE_KEY = "sprints_list"
KANBAN_STATE_KEY_PREFIX = "kanban_state_"
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

_dragged_backlog_id = None


# Load persisted product-backlog tasks, seeding the starter tasks on first visit.
def load_backlog_items():
    raw = window.localStorage.getItem(BACKLOG_STORAGE_KEY)
    if not raw:
        seeded = list(DEFAULT_BACKLOG_ITEMS)
        save_backlog_items(seeded)
        return seeded
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return list(DEFAULT_BACKLOG_ITEMS)


# Save product-backlog tasks in browser storage.
def save_backlog_items(items):
    window.localStorage.setItem(BACKLOG_STORAGE_KEY, json.dumps(items))


# Read and write the backlog handoff associated with an individual sprint.
def load_sprint_backlog(sprint_id):
    raw = window.localStorage.getItem(f"{SPRINT_BACKLOG_KEY_PREFIX}{sprint_id}")
    if not raw:
        return []
    try:
        return json.loads(raw)
    except ValueError:
        return []


def save_sprint_backlog(sprint_id, items):
    window.localStorage.setItem(f"{SPRINT_BACKLOG_KEY_PREFIX}{sprint_id}", json.dumps(items))


def add_item_to_sprint_backlog(sprint_id, item):
    items = load_sprint_backlog(sprint_id)
    items.append(item)
    save_sprint_backlog(sprint_id, items)
    return len(items)


# Build one draggable product-backlog task card.
def _make_backlog_card(item):
    card = document.createElement("div")
    card.className = "task-card"
    card.id = f"backlog-item-{item['id']}"
    card.setAttribute("draggable", "true")
    card.setAttribute("data-backlog-id", item["id"])
    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{item['tag']}">{item['tag'].capitalize()}</span>
        </div>
        <p class="task-card-title">{item['title']}</p>
        <div class="task-card-footer">
            <span class="priority-badge priority-{item['priority']}">{item['priority'].capitalize()}</span>
        </div>
    """
    return card


# Render all product-backlog cards and update their displayed count.
def render_backlog_list():
    items = load_backlog_items()
    list_el = web.page["backlog-list"]
    list_el.innerHTML = ""
    for item in items:
        list_el.appendChild(_make_backlog_card(item))
    web.page["count-product-backlog"].textContent = str(len(items))


# Refresh one sprint card's count of items waiting to enter its Kanban board.
def _refresh_card_badge(sprint_id):
    badge = web.page[f"backlog-count-{sprint_id}"]
    if badge is not None:
        count = len(load_sprint_backlog(sprint_id))
        badge.textContent = f"{count} backlog item{'s' if count != 1 else ''}"


def _refresh_all_card_badges():
    for card in document.querySelectorAll(".sprint-card"):
        sprint_id = card.getAttribute("data-sprint-id")
        if sprint_id:
            _refresh_card_badge(sprint_id)


@when("dragstart", "#backlog-list")
def handle_drag_start(event):
    # Store the dragged task ID so a sprint-card drop can find its backlog record.
    global _dragged_backlog_id
    card = event.target.closest(".task-card")
    if not card:
        return
    backlog_id = card.getAttribute("data-backlog-id")
    if not backlog_id:
        return
    _dragged_backlog_id = backlog_id
    event.dataTransfer.setData("text/plain", backlog_id)
    event.dataTransfer.effectAllowed = "move"
    card.classList.add("dragging")


@when("dragend", "#backlog-list")
def handle_drag_end(event):
    # Remove the drag highlight and clear the active task ID.
    global _dragged_backlog_id
    card = event.target.closest(".task-card")
    if card:
        card.classList.remove("dragging")
    _dragged_backlog_id = None


@when("dragover", ".sprints-grid")
def handle_card_drag_over(event):
    # Allow drops on sprint cards and highlight the current target.
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    card = event.target.closest(".sprint-card")
    if card:
        card.classList.add("card-drop-target")


@when("dragleave", ".sprints-grid")
def handle_card_drag_leave(event):
    # Clear the target highlight after the dragged item leaves a sprint card.
    card = event.target.closest(".sprint-card")
    if card:
        card.classList.remove("card-drop-target")


@when("drop", ".sprints-grid")
def handle_card_drop(event):
    # Move the item immediately, then write its activity event without blocking the UI.
    event.preventDefault()
    card = event.target.closest(".sprint-card")
    if not card:
        return
    card.classList.remove("card-drop-target")
    if _dragged_backlog_id is None:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return

    items = load_backlog_items()
    matching = next((item for item in items if item["id"] == _dragged_backlog_id), None)
    if matching is None:
        return

    remaining = [item for item in items if item["id"] != _dragged_backlog_id]
    save_backlog_items(remaining)
    add_item_to_sprint_backlog(sprint_id, matching)
    sprint = next((item for item in load_sprints() if item["id"] == sprint_id), {})

    dragged_el = web.page[f"backlog-item-{_dragged_backlog_id}"]
    if dragged_el is not None:
        dragged_el.remove()
    web.page["count-product-backlog"].textContent = str(len(remaining))
    _refresh_card_badge(sprint_id)

    asyncio.ensure_future(record_change(
        f"added {matching['title']} to {sprint.get('name', 'a sprint')}",
        sprint_id,
        sprint.get("name"),
        matching.get("id"),
        matching.get("title"),
    ))


# Load and save the dashboard's sprint list, using starter sprints when needed.
def load_sprints():
    raw = window.localStorage.getItem(SPRINTS_STORAGE_KEY)
    if not raw:
        seeded = list(DEFAULT_SPRINTS)
        save_sprints(seeded)
        return seeded
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return list(DEFAULT_SPRINTS)


def save_sprints(items):
    window.localStorage.setItem(SPRINTS_STORAGE_KEY, json.dumps(items))


# Build one sprint card with its current state and backlog count target.
def _make_sprint_card(item):
    card = document.createElement("div")
    card.className = "sprint-card"
    card.setAttribute("data-sprint-id", item["id"])
    status_label = "Active" if item["status"] == "active" else "Ended"
    card.innerHTML = f"""
        <h3 class="sprint-title">{item['name']}</h3>
        <p class="sprint-details">{item['details']}</p>
        <div class="sprint-footer">
            <span class="status-badge status-{item['status']}">{status_label}</span>
            <button class="burndown-button">Chart</button>
        </div>
    """
    return card


# Refresh the sprint grid from saved sprint records.
def render_sprints_grid():
    items = load_sprints()
    grid = document.querySelector(".sprints-grid")
    grid.innerHTML = ""
    for item in items:
        grid.appendChild(_make_sprint_card(item))


# Read history events from IndexedDB and convert JavaScript records to Python objects.
async def _load_change_history():
    entries = await window.sprintHistoryDb.getAll()
    return json.loads(str(js.JSON.stringify(entries)))


# Resolve the active account to a readable actor name for new events.
def _current_actor():
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


# Store a timestamped dashboard event in the shared IndexedDB database.
async def record_change(message, sprint_id=None, sprint_name=None, task_id=None, task_title=None):
    actor = _current_actor()
    entry = {
        "action": "project_change",
        "message": f"{actor} {message}",
        "sprint_id": sprint_id,
        "sprint_name": sprint_name,
        "task_id": task_id,
        "task_title": task_title,
        "actor": actor,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    await window.sprintHistoryDb.add(js.JSON.parse(json.dumps(entry)))


# Render activity newest-first and show a message when the database is empty.
async def render_change_history():
    history = await _load_change_history()
    history_list = web.page["history-list"]
    history_list.innerHTML = ""
    if not history:
        empty = document.createElement("li")
        empty.className = "feature-empty-state"
        empty.textContent = "No changes have been recorded yet."
        history_list.appendChild(empty)
        return

    for entry in reversed(history):
        row = document.createElement("li")
        row.className = "activity-row"
        summary = document.createElement("p")
        summary.className = "activity-summary"
        if entry.get("message"):
            summary.textContent = entry["message"]
        elif entry.get("action") == "moved":
            summary.textContent = f"{entry.get('actor', 'Unknown user')} moved {entry.get('task_title', 'a task')} from {entry.get('from_status', 'unknown')} to {entry.get('to_status', 'unknown')} in {entry.get('sprint_name', 'a sprint')}"
        else:
            summary.textContent = f"{entry.get('actor', 'Unknown user')} ended {entry.get('sprint_name', 'a sprint')}"
        metadata = document.createElement("span")
        metadata.className = "activity-metadata"
        metadata.textContent = entry.get("timestamp", "")
        row.appendChild(summary)
        row.appendChild(metadata)
        history_list.appendChild(row)


# Load one sprint board, falling back to its sample state before first use.
def _load_kanban_state(sprint_id):
    raw = window.localStorage.getItem(f"{KANBAN_STATE_KEY_PREFIX}{sprint_id}")
    if not raw:
        return DEFAULT_KANBAN_STATES.get(sprint_id, {column: [] for column in COLUMN_ORDER})
    try:
        state = json.loads(raw)
    except (ValueError, TypeError):
        return DEFAULT_KANBAN_STATES.get(sprint_id, {column: [] for column in COLUMN_ORDER})
    for column in COLUMN_ORDER:
        state.setdefault(column, [])
    return state


# Match abbreviated seeded assignee names to full names in the member roster.
def _member_name_for_assignee(assignee, members):
    normalized = assignee.strip().casefold()
    for name in members:
        candidate = name.casefold()
        if candidate == normalized or candidate.endswith(f" {normalized}"):
            return name
    return assignee


# Aggregate assigned tasks and completed counts for every member across sprints.
def render_member_contributions():
    members = [
        button.getAttribute("data-member-name")
        for button in document.querySelectorAll(".member-trigger")
        if button.getAttribute("data-member-name")
    ]
    contributions = {
        name: {"assigned": 0, "completed": 0, "tasks": []}
        for name in members
    }

    for sprint in load_sprints():
        state = _load_kanban_state(sprint["id"])
        for column in COLUMN_ORDER:
            for task in state[column]:
                assignee = task.get("assignee")
                if not assignee:
                    continue
                name = _member_name_for_assignee(assignee, members)
                contribution = contributions.setdefault(
                    name, {"assigned": 0, "completed": 0, "tasks": []}
                )
                contribution["assigned"] += 1
                if column == "completed":
                    contribution["completed"] += 1
                contribution["tasks"].append({
                    "title": task.get("title", "Untitled task"),
                    "status": column,
                    "sprint": sprint.get("name", "Sprint"),
                })

    contribution_list = web.page["contribution-list"]
    contribution_list.innerHTML = ""
    ranked = sorted(
        contributions.items(),
        key=lambda item: (-item[1]["assigned"], item[0].casefold()),
    )
    for name, stats in ranked:
        card = document.createElement("section")
        card.className = "contribution-row"
        heading = document.createElement("h2")
        heading.className = "contribution-name"
        heading.textContent = name
        metrics = document.createElement("p")
        metrics.className = "contribution-metrics"
        metrics.textContent = f"{stats['assigned']} assigned · {stats['completed']} completed"
        tasks = document.createElement("ul")
        tasks.className = "contribution-tasks"
        if stats["tasks"]:
            for task in stats["tasks"]:
                task_row = document.createElement("li")
                is_completed = task["status"] == "completed"
                task_row.className = "contribution-task completed" if is_completed else "contribution-task incomplete"
                task_title = document.createElement("span")
                task_title.className = "contribution-task-title"
                task_title.textContent = task["title"]
                task_status = document.createElement("span")
                task_status.className = "contribution-task-status"
                if is_completed:
                    task_status.textContent = f"Completed · {task['sprint']}"
                else:
                    task_status.textContent = f"Not completed · {task['status'].capitalize()} · {task['sprint']}"
                task_row.appendChild(task_title)
                task_row.appendChild(task_status)
                tasks.appendChild(task_row)
        else:
            tasks.classList.add("empty")
            tasks.textContent = "No assigned tasks"
        card.appendChild(heading)
        card.appendChild(metrics)
        card.appendChild(tasks)
        contribution_list.appendChild(card)


# Display one dashboard panel and keep its navigation item and layout in sync.
def _show_dashboard_view(view_id):
    view_ids = ["sprints-view", "members-view", "history-view", "contributions-view"]
    nav_ids = ["nav-all-projects", "nav-members", "nav-history", "nav-contributions"]
    is_feature_view = view_id != "sprints-view"
    document.querySelector(".sprint-dashboard-layout").classList.toggle("members-open", is_feature_view)
    for current_view in view_ids:
        web.page[current_view].classList.toggle("hidden", current_view != view_id)
    active_nav = {
        "sprints-view": "nav-all-projects",
        "members-view": "nav-members",
        "history-view": "nav-history",
        "contributions-view": "nav-contributions",
    }[view_id]
    for nav_id in nav_ids:
        web.page[nav_id].classList.toggle("active", nav_id == active_nav)


@when("click", "#nav-all-projects")
def handle_show_sprints(event):
    # Return to the sprint grid and restore the product-backlog sidebar.
    _show_dashboard_view("sprints-view")


@when("click", "#nav-members")
def handle_show_members(event):
    # Open the sprint member roster.
    _show_dashboard_view("members-view")


@when("click", "#nav-history")
async def handle_show_history(event):
    # Refresh saved events before opening the history panel.
    await render_change_history()
    _show_dashboard_view("history-view")


@when("click", "#nav-contributions")
def handle_show_contributions(event):
    # Recalculate task totals before opening the contribution panel.
    render_member_contributions()
    _show_dashboard_view("contributions-view")


# Open and close shared dashboard modal overlays by element ID.
def _open_modal(modal_id):
    web.page[modal_id].classList.remove("hidden")


def _close_modal(modal_id):
    web.page[modal_id].classList.add("hidden")


@when("click", ".member-list")
def handle_member_click(event):
    # Populate the contact dialog from the selected member's data attributes.
    trigger = event.target.closest(".member-trigger")
    if trigger is None:
        return
    web.page["member-modal-name"].textContent = trigger.getAttribute("data-member-name") or "Not provided"
    web.page["member-modal-phone"].textContent = trigger.getAttribute("data-member-phone") or "Not provided"
    web.page["member-modal-email"].textContent = trigger.getAttribute("data-member-email") or "Not provided"
    _open_modal("member-details-modal")
    web.page["close-member-details"].focus()


@when("click", "#close-member-details")
def handle_close_member_details(event):
    # Close the member contact dialog.
    _close_modal("member-details-modal")


@when("click", "#create-sprint-btn")
def handle_open_create_sprint(event):
    _open_modal("create-sprint-modal")


@when("click", "#create-task-button")
def handle_open_create_task(event):
    _open_modal("create-task-modal")


@when("click", ".modal-btn-cancel")
def handle_cancel_modal(event):
    _close_modal(event.currentTarget.getAttribute("data-modal"))


@when("click", ".modal-overlay")
def handle_backdrop_click(event):
    if event.target.id == event.currentTarget.id:
        _close_modal(event.currentTarget.id)


# Validate and persist new sprint records from the create-sprint dialog.
@when("submit", "#create-sprint-form")
async def handle_create_sprint_submit(event):
    event.preventDefault()
    name = web.page["sprint-name-input"].value.strip()
    details = web.page["sprint-details-input"].value.strip()
    status = web.page["sprint-status-input"].value
    if not name:
        return

    items = load_sprints()
    new_id = str(int(time.time() * 1000))
    items.append({"id": new_id, "name": name, "details": details or "No description", "status": status})
    save_sprints(items)
    await record_change(f"created sprint {name}", new_id, name)
    render_sprints_grid()
    event.currentTarget.reset()
    _close_modal("create-sprint-modal")


# Validate and persist new product-backlog tasks from the create-task dialog.
@when("submit", "#create-task-form")
async def handle_create_task_submit(event):
    event.preventDefault()
    title = web.page["task-title-input"].value.strip()
    tag = web.page["task-tag-input"].value
    priority = web.page["task-priority-input"].value
    if not title:
        return

    items = load_backlog_items()
    new_id = str(int(time.time() * 1000))
    items.append({"id": new_id, "title": title, "tag": tag, "priority": priority})
    save_backlog_items(items)
    await record_change(f"created backlog task {title}", task_id=new_id, task_title=title)
    render_backlog_list()
    event.currentTarget.reset()
    _close_modal("create-task-modal")


@when("click", ".sprints-grid")
def handle_sprint_card_click(event):
    # Open the selected sprint board unless the chart control was clicked.
    if event.target.closest(".burndown-button"):
        return
    card = event.target.closest(".sprint-card")
    if not card:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return
    window.location.href = f"sprint-page.html?sprint_id={sprint_id}"


# Build the initial dashboard from saved sprint and backlog data.
render_sprints_grid()
render_backlog_list()
_refresh_all_card_badges()
asyncio.ensure_future(render_change_history())
render_member_contributions()

# Restore the panel requested by a sprint-page sidebar link, or open its modal.
dashboard_params = js.URLSearchParams.new(window.location.search)
requested_view = dashboard_params.get("view")
view_ids = {
    "sprints": "sprints-view",
    "members": "members-view",
    "history": "history-view",
    "contributions": "contributions-view",
}
if requested_view in view_ids:
    if requested_view == "history":
        asyncio.ensure_future(render_change_history())
    elif requested_view == "contributions":
        render_member_contributions()
    _show_dashboard_view(view_ids[requested_view])

requested_modal = dashboard_params.get("modal")
if requested_modal == "create-sprint-modal":
    _open_modal(requested_modal)