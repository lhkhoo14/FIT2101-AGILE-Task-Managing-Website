import sys
import asyncio
import json
import time
from html import escape

if "." not in sys.path:
    sys.path.append(".")

from datetime import datetime

from pyscript import when, web, window, document  # type: ignore[reportMissingImports]
from auth import show_snackbar
import js  # type: ignore[reportMissingImports]
from server_data import ServerData

# ServerData is the client-side gateway for all sprint-dashboard API calls.
# The dashboard never owns sprint data; it asks FastAPI for the current project
# state and re-renders the affected UI after successful mutations.
server_data = ServerData()
from sprint_access import (
    is_sprint_member, sort_sprints, normalize_tags, filter_sprints_by_tag,
    PRIORITY_ORDER, DEFAULT_PRIORITY,
)

COLUMN_ORDER = ["backlog", "active", "review", "completed"]

# The project ID scopes every dashboard API request. The <head> guard has
# already ensured the URL carries a valid project_id (restoring the last project
# opened in this tab when the query is missing), so this only sanity-checks it.
url_params = window.URLSearchParams.new(window.location.search)
project_id_param = url_params.get("project_id")
if not project_id_param or not project_id_param.isdigit():
    window.location.replace("dashboard.html")
    PROJECT_ID = 0
else:
    PROJECT_ID = int(project_id_param)

_dragged_backlog_id = None

# --- CURRENT USER (sprint membership checks) ---
_session = server_data.get_active_session()
current_user_id = int(_session) if _session else None


# --- User / member helpers ---
def _display_name(user):
    return user.get("username") or user.get("email") or f"User {user.get('user_id')}"


def _initials(name):
    parts = name.replace("@", " ").replace(".", " ").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


async def _users_by_id(sprints):
    user_ids = {
        int(user_id)
        for sprint in sprints
        for user_id in (sprint.get("members") or [])
        if str(user_id).isdigit()
    }
    users = await server_data.get_users()
    return {
        int(user["user_id"]): user
        for user in users
        if int(user["user_id"]) in user_ids
    }


def _notify(message):
    asyncio.ensure_future(show_snackbar(message))


# Build one draggable product-backlog task card.
def _make_backlog_card(item):
    card = document.createElement("div")
    card.className = "task-card"
    card.id = f"backlog-item-{item['id']}"
    card.setAttribute("draggable", "true")
    card.setAttribute("data-backlog-id", str(item["id"]))
    tag = str(item.get("tag", "frontend")).lower()
    priority = str(item.get("priority", "medium")).lower()
    title = escape(str(item.get("title", "")))
    card.innerHTML = f"""
        <div class="task-card-header">
            <span class="tag-badge tag-{tag}">{tag.capitalize()}</span>
        </div>
        <p class="task-card-title">{title}</p>
        <div class="task-card-footer">
            <span class="priority-badge priority-{priority}">{priority.capitalize()}</span>
        </div>
    """
    return card


# Render all product-backlog cards and update their displayed count.
async def render_backlog_list():
    """Fetch the product backlog from FastAPI and rebuild its sidebar list."""
    if not PROJECT_ID:
        return
    items = await server_data.get_backlog_items(PROJECT_ID)
    list_el = document.getElementById("backlog-list")
    if list_el is not None:
        list_el.innerHTML = ""
        for item in items:
            list_el.appendChild(_make_backlog_card(item))
    count_el = document.getElementById("count-product-backlog")
    if count_el is not None:
        count_el.textContent = str(len(items))


# Refresh one sprint card's count of items waiting to enter its Kanban board.
async def _refresh_card_badge(sprint_id):
    badge = document.getElementById(f"backlog-count-{sprint_id}")
    if badge is not None and PROJECT_ID:
        items = await server_data.get_sprint_backlog(PROJECT_ID, sprint_id)
        count = len(items)
        badge.textContent = f"{count} backlog item{'s' if count != 1 else ''}"


async def _refresh_all_card_badges():
    refreshes = []
    for card in document.querySelectorAll(".sprint-card"):
        sprint_id = card.getAttribute("data-sprint-id")
        if sprint_id:
            refreshes.append(_refresh_card_badge(sprint_id))
    if refreshes:
        await asyncio.gather(*refreshes)


# --- Drag and Drop Logic ---
@when("dragstart", "#backlog-list")
def handle_drag_start(event):
    # Store the dragged task ID so a sprint-card drop can find its backlog record.
    global _dragged_backlog_id
    _dragged_backlog_id = None
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
    # Remove the drag highlight; the drop handler consumes the task ID.
    card = event.target.closest(".task-card")
    if card:
        card.classList.remove("dragging")


@when("dragover", ".sprints-grid")
def handle_card_drag_over(event):
    # Allow drops on sprint cards and highlight the current target.
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    card = event.target.closest(".sprint-card")
    if card:
        if card.getAttribute("data-member") == "true":
            card.classList.add("card-drop-target")
        else:
            card.classList.add("card-drop-denied")


@when("dragleave", ".sprints-grid")
def handle_card_drag_leave(event):
    # Clear the target highlight after the dragged item leaves a sprint card.
    card = event.target.closest(".sprint-card")
    if card:
        card.classList.remove("card-drop-target")
        card.classList.remove("card-drop-denied")


@when("drop", ".sprints-grid")
async def handle_card_drop(event):
    # Validate membership with the API-backed sprint record, then ask FastAPI
    # to atomically move the backlog item into that sprint's Kanban backlog.
    event.preventDefault()
    card = event.target.closest(".sprint-card")
    if not card:
        return
    card.classList.remove("card-drop-target")
    card.classList.remove("card-drop-denied")

    global _dragged_backlog_id
    backlog_id = _dragged_backlog_id
    _dragged_backlog_id = None
    if backlog_id is None:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return

    # Only assigned members may drop tasks into a sprint. Checked against
    # storage (not the card's data attribute) so it can't be bypassed via the DOM.
    sprints = await server_data.get_sprints(PROJECT_ID)
    sprint = next((s for s in sprints if str(s.get("id")) == str(sprint_id)), None)
    if sprint is None or not is_sprint_member(sprint, current_user_id):
        _notify("You are not assigned to this sprint, so you can't add tasks to it.")
        return

    success, err = await server_data.move_backlog_item_to_sprint(
        PROJECT_ID, backlog_id, sprint_id
    )
    if not success:
        _notify(err)
        return

    await render_backlog_list()
    await _refresh_card_badge(sprint_id)

    asyncio.ensure_future(record_change(
        f"added a backlog task to {sprint.get('name', 'a sprint')}",
        sprint_id,
        sprint.get("name"),
        backlog_id,
    ))


# --- Sprint rendering ---
# Build one sprint card with its current state and backlog count target.
_LOCK_ICON = (
    '<svg viewBox="0 0 24 24" class="icon"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 '
    '.9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-6 9c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 '
    '2-2 2zm3.1-9H8.9V6c0-1.71 1.39-3.1 3.1-3.1 1.71 0 3.1 1.39 3.1 3.1v2z"/></svg>'
)


def _members_html(item, users):
    members = item.get("members")
    if members is None:  # legacy sprint, open to everyone
        return '<span class="members-open">Open to all users</span>'
    names = [_display_name(users[m]) if m in users else "Unknown user" for m in members]
    html = "".join(
        f'<span class="sprint-member-avatar" title="{escape(n)}">{escape(_initials(n))}</span>'
        for n in names[:4]
    )
    extra = len(names) - 4
    if extra > 0:
        html += f'<span class="sprint-member-avatar sprint-member-avatar-more" title="{extra} more">+{extra}</span>'
    return html


def _make_sprint_card(item, users):
    is_member = is_sprint_member(item, current_user_id)
    status = item.get("status", "active")
    priority = item.get("priority", DEFAULT_PRIORITY)
    if priority not in PRIORITY_ORDER:
        priority = DEFAULT_PRIORITY

    card = document.createElement("div")
    card.className = "sprint-card" if is_member else "sprint-card sprint-card-locked"
    card.setAttribute("data-sprint-id", item["id"])
    card.setAttribute("data-member", "true" if is_member else "false")

    status_label = "Active" if status == "active" else "Ended"
    lock_html = (
        f'<span class="lock-badge" title="You are not assigned to this sprint">{_LOCK_ICON}Members only</span>'
        if not is_member else ""
    )
    tags_html = "".join(
        f'<span class="sprint-tag-chip">{escape(str(tag))}</span>' for tag in (item.get("tags") or [])
    )
    tags_block = f'<div class="sprint-tags">{tags_html}</div>' if tags_html else ""

    card.innerHTML = f"""
        <h3 class="sprint-title">{escape(item['name'])}</h3>
        <p class="sprint-details">{escape(item.get('details', ''))}</p>
        {tags_block}
        <div class="sprint-members">{_members_html(item, users)}{lock_html}</div>
        <div class="sprint-footer">
            <div class="sprint-badges">
                <span class="status-badge status-{status}">{status_label}</span>
                <span class="priority-badge priority-{priority}">{priority.capitalize()}</span>
            </div>
            <button class="burndown-button">Chart</button>
        </div>
    """
    return card


# Refresh the sprint grid from saved sprint records.
async def render_sprints_grid():
    """Fetch, filter, sort, and render the project's sprint cards."""
    sort_select = web.page["sort-select"]
    sort_key = sort_select.value if sort_select is not None else "date"
    search_input = web.page["global-search"]
    query = search_input.value.strip() if search_input is not None else ""

    all_items = await server_data.get_sprints(PROJECT_ID)
    items = sort_sprints(filter_sprints_by_tag(all_items, query), sort_key)
    users = await _users_by_id(items)
    grid = document.querySelector(".sprints-grid")
    grid.innerHTML = ""
    for item in items:
        grid.appendChild(_make_sprint_card(item, users))

    if query and not items:
        empty = document.createElement("p")
        empty.className = "sprints-empty"
        empty.textContent = f'No sprints have a tag matching "{query}".'
        grid.appendChild(empty)


@when("input", "#global-search")
def handle_search_input(event):
    render_sprints_grid()


@when("change", "#sort-select")
def handle_sort_change(event):
    render_sprints_grid()


# History is still a browser-only activity feed. Sprint/project data itself is
# not stored here; it comes from FastAPI through ServerData.
async def _load_change_history():
    entries = await window.sprintHistoryDb.getAll()
    return json.loads(str(js.JSON.stringify(entries)))


# Resolve the active account to a readable actor name for new events.
async def _current_actor():
    user_id = server_data.get_active_session()
    user = await server_data.get_user_by_id(user_id) if user_id is not None else None
    return (user.get("username") or user.get("email")) if user else "Unknown user"


# Store a timestamped dashboard event in the shared IndexedDB database.
async def record_change(message, sprint_id=None, sprint_name=None, task_id=None, task_title=None):
    actor = await _current_actor()
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


# Match abbreviated seeded assignee names to full names in the member roster.
def _member_name_for_assignee(assignee, members):
    normalized = assignee.strip().casefold()
    for name in members:
        candidate = name.casefold()
        if candidate == normalized or candidate.endswith(f" {normalized}"):
            return name
    return assignee


# Render the project member roster from the real project members.
async def render_members_view():
    team = await server_data.get_project_team(PROJECT_ID)
    list_el = document.getElementById("sprint-member-list")
    if list_el is None:
        return
    list_el.innerHTML = ""

    count_el = document.getElementById("member-count")
    if count_el is not None:
        count_el.textContent = f"{len(team)} member{'s' if len(team) != 1 else ''}"

    if not team:
        empty = document.createElement("li")
        empty.className = "feature-empty-state"
        empty.textContent = "No project members found."
        list_el.appendChild(empty)
        return

    for member in team:
        name = member.get("username") or member.get("email") or "Unknown user"
        email = member.get("email", "")
        row = document.createElement("li")
        row.className = "member-row"
        row.innerHTML = (
            f'<button type="button" class="member-trigger" '
            f'data-member-name="{escape(name)}" data-member-phone="" '
            f'data-member-email="{escape(email)}">'
            f'<span class="member-avatar" aria-hidden="true">{escape(_initials(name))}</span>'
            f'<span class="member-details"><strong>{escape(name)}</strong>'
            f'<span>{escape(email)}</span></span></button>'
        )
        list_el.appendChild(row)


# Aggregate assigned tasks and completed counts for every member across sprints.
async def render_member_contributions():
    team = await server_data.get_project_team(PROJECT_ID)
    members = [
        member.get("username") or member.get("email")
        for member in team
        if member.get("username") or member.get("email")
    ]
    contributions = {
        name: {"assigned": 0, "completed": 0, "tasks": []}
        for name in members
    }

    sprints = await server_data.get_sprints(PROJECT_ID)
    for sprint in sprints:
        state = await server_data.get_kanban_state(PROJECT_ID, sprint["id"])
        if state is None:
            continue
        for column in COLUMN_ORDER:
            for task in state.get(column, []):
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


# Switch the visible dashboard panel without navigating away from the page.
# History and contribution data are fetched only when their panels are opened.
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
async def handle_show_members(event):
    # Render the live roster, then open the members panel.
    await render_members_view()
    _show_dashboard_view("members-view")


@when("click", "#nav-history")
async def handle_show_history(event):
    # Refresh saved events before opening the history panel.
    await render_change_history()
    _show_dashboard_view("history-view")


@when("click", "#nav-contributions")
async def handle_show_contributions(event):
    # Recalculate task totals before opening the contribution panel.
    await render_member_contributions()
    _show_dashboard_view("contributions-view")


@when("app:sprint-dashboard-navigation", "body")
async def handle_sprint_page_navigation(event):
    """Handle navigation messages from the sprint board iframe."""
    detail = event.detail
    if detail.action == "create-sprint":
        await _render_member_options()
        _open_modal("create-sprint-modal")
        return

    view_ids = {
        "sprints": "sprints-view",
        "members": "members-view",
        "history": "history-view",
        "contributions": "contributions-view",
    }
    view_id = view_ids.get(detail.view)
    if view_id is None:
        return
    if detail.view == "history":
        await render_change_history()
    elif detail.view == "members":
        await render_members_view()
    elif detail.view == "contributions":
        await render_member_contributions()
    _show_dashboard_view(view_id)


# Open and close shared dashboard modal overlays by element ID.
def _open_modal(modal_id):
    web.page[modal_id].classList.remove("hidden")


def _close_modal(modal_id):
    web.page[modal_id].classList.add("hidden")


async def _render_member_options():
    """Fill the create-sprint modal with one checkbox per registered user."""
    users = await server_data.get_users()
    container = web.page["sprint-members-list"]
    container.innerHTML = ""

    for user in users:
        uid = user["user_id"]
        is_self = uid == current_user_id
        name = _display_name(user) + (" (you)" if is_self else "")
        label = document.createElement("label")
        label.className = "member-option"
        label.innerHTML = (
            f'<input type="checkbox" value="{uid}"{" checked disabled" if is_self else ""}>'
            f'<span class="member-option-avatar">{escape(_initials(_display_name(user)))}</span>'
            f'<span class="member-option-name">{escape(name)}</span>'
        )
        container.appendChild(label)

    if len(users) <= 1:
        empty = document.createElement("p")
        empty.className = "members-empty"
        empty.textContent = "No other registered users yet."
        container.appendChild(empty)


def _selected_member_ids():
    ids = []
    for box in document.querySelectorAll("#sprint-members-list input[type=checkbox]"):
        if box.checked:
            ids.append(int(box.value))
    # The creator is always a member, even if their checkbox state is lost.
    if current_user_id is not None and current_user_id not in ids:
        ids.insert(0, current_user_id)
    return ids


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
async def handle_open_create_sprint(event):
    await _render_member_options()
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
    """Validate the form and create the sprint through FastAPI."""
    if event:
        event.preventDefault()
    name = web.page["sprint-name-input"].value.strip()
    details = web.page["sprint-details-input"].value.strip()
    priority = web.page["sprint-priority-input"].value
    if priority not in PRIORITY_ORDER:
        priority = DEFAULT_PRIORITY

    if not name:
        return
    if not PROJECT_ID:
        _notify("Open this sprint dashboard from a project first.")
        return

    now_ms = int(time.time() * 1000)
    tags = normalize_tags(web.page["sprint-tags-input"].value)
    members = _selected_member_ids()
    success, err, sprint = await server_data.create_sprint(
        PROJECT_ID,
        name,
        details or "No description",
        "active",
        priority=priority,
        tags=tags,
        members=members,
        created_at=now_ms,
    )
    if not success or sprint is None:
        _notify(err)
        return

    await record_change(f"created sprint {name}", sprint["id"], name)
    await render_sprints_grid()
    form = document.getElementById("create-sprint-form")
    if form:
        form.reset()
    _close_modal("create-sprint-modal")


# Validate and persist new product-backlog tasks from the create-task dialog.
@when("submit", "#create-task-form")
async def handle_create_task_submit(event):
    """Create a product-backlog item and refresh the list after the API responds."""
    if event:
        event.preventDefault()
    title = web.page["task-title-input"].value.strip()
    tag = web.page["task-tag-input"].value
    priority = web.page["task-priority-input"].value
    if not title:
        return
    if not PROJECT_ID:
        _notify("Open this sprint dashboard from a project first.")
        return

    form = document.getElementById("create-task-form")
    submit_button = form.querySelector("button[type='submit']") if form else None
    if submit_button is not None:
        submit_button.disabled = True

    try:
        success, err, item = await server_data.create_backlog_item(
            PROJECT_ID, title, tag, priority
        )
        if not success:
            _notify(err)
            return

        await render_backlog_list()
        if form:
            form.reset()
        _close_modal("create-task-modal")
        asyncio.ensure_future(record_change(
            f"created backlog task {title}",
            task_id=item.get("id") if item else None,
            task_title=title,
        ))
    finally:
        if submit_button is not None:
            submit_button.disabled = False


@when("click", ".sprints-grid")
async def handle_sprint_card_click(event):
    # Open the selected sprint board unless the chart control was clicked.
    # The dashboard keeps one hidden iframe warm so this transition does not
    # restart PyScript for every sprint selection.
    if event.target.closest(".burndown-button"):
        return
    card = event.target.closest(".sprint-card")
    if not card:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return
    sprints = await server_data.get_sprints(PROJECT_ID)
    sprint = next((s for s in sprints if str(s.get("id")) == str(sprint_id)), None)
    if sprint is None or not is_sprint_member(sprint, current_user_id):
        _notify("You are not assigned to this sprint.")
        return

    window.openSprintBoard(sprint_id)


# Initial load: fetch the sprint cards first, warm the board iframe, then fetch
# the backlog and its per-sprint counts. All persistent data comes from FastAPI.
async def initialize_dashboard():
    if not PROJECT_ID:
        return
    await render_sprints_grid()
    first_available_card = document.querySelector('.sprint-card[data-member="true"]')
    if first_available_card:
        window.prepareSprintBoard(first_available_card.getAttribute("data-sprint-id"))
    await render_backlog_list()
    await _refresh_all_card_badges()

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
    elif requested_view == "members":
        asyncio.ensure_future(render_members_view())
    elif requested_view == "contributions":
        asyncio.ensure_future(render_member_contributions())
    _show_dashboard_view(view_ids[requested_view])

requested_modal = dashboard_params.get("modal")
if requested_modal == "create-sprint-modal":
    _open_modal(requested_modal)

# A redirect can carry a short user-facing message without browser storage.
message = dashboard_params.get("message")
if message:
    _notify(message)

asyncio.ensure_future(initialize_dashboard())