import asyncio
from pyscript import when, web, window, document  # type: ignore[reportMissingImports]
from server_data import ServerData

server_data = ServerData()

# Retrieve active project_id from URL query params or default to 1
url_params = window.URLSearchParams.new(window.location.search)
PROJECT_ID = int(url_params.get("project_id") or 1)

_dragged_backlog_id = None


# --- Rendering the Backlog List ---
def _make_backlog_card(item):
    card = document.createElement("div")
    card.className = "task-card"
    card.id = f"backlog-item-{item['id']}"
    card.setAttribute("draggable", "true")
    card.setAttribute("data-backlog-id", str(item["id"]))

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


async def render_backlog_list():
    items = await server_data.get_backlog_items(PROJECT_ID)
    list_el = web.page["backlog-list"]
    list_el.innerHTML = ""
    for item in items:
        list_el.appendChild(_make_backlog_card(item))
    web.page["count-product-backlog"].textContent = str(len(items))


async def _refresh_card_badge(sprint_id):
    badge = web.page[f"backlog-count-{sprint_id}"]
    if badge is not None:
        items = await server_data.get_sprint_backlog(PROJECT_ID, sprint_id)
        count = len(items)
        badge.textContent = f"{count} backlog item{'s' if count != 1 else ''}"


async def _refresh_all_card_badges():
    for card in document.querySelectorAll(".sprint-card"):
        sprint_id = card.getAttribute("data-sprint-id")
        if sprint_id:
            await _refresh_card_badge(sprint_id)


# --- Drag and Drop Logic ---
@when("dragstart", "#backlog-list")
def handle_drag_start(event):
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
    global _dragged_backlog_id
    card = event.target.closest(".task-card")
    if card:
        card.classList.remove("dragging")
    _dragged_backlog_id = None


@when("dragover", ".sprints-grid")
def handle_card_drag_over(event):
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    card = event.target.closest(".sprint-card")
    if card:
        card.classList.add("card-drop-target")


@when("dragleave", ".sprints-grid")
def handle_card_drag_leave(event):
    card = event.target.closest(".sprint-card")
    if card:
        card.classList.remove("card-drop-target")


@when("drop", ".sprints-grid")
def handle_card_drop(event):
    event.preventDefault()
    card = event.target.closest(".sprint-card")
    if not card:
        return
    card.classList.remove("card-drop-target")

    global _dragged_backlog_id
    if _dragged_backlog_id is None:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return

    backlog_id = _dragged_backlog_id
    _dragged_backlog_id = None

    async def process_move():
        success, err = await server_data.move_backlog_item_to_sprint(PROJECT_ID, backlog_id, sprint_id)
        if success:
            dragged_el = web.page[f"backlog-item-{backlog_id}"]
            if dragged_el is not None:
                dragged_el.remove()
            await render_backlog_list()
            await _refresh_card_badge(sprint_id)

    asyncio.ensure_future(process_move())


# --- Sprint rendering ---
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


async def render_sprints_grid():
    items = await server_data.get_sprints(PROJECT_ID)
    grid = document.querySelector(".sprints-grid")
    grid.innerHTML = ""
    for item in items:
        grid.appendChild(_make_sprint_card(item))


# --- Modal open/close ---
def _open_modal(modal_id):
    web.page[modal_id].classList.remove("hidden")


def _close_modal(modal_id):
    web.page[modal_id].classList.add("hidden")


@when("click", "#create-sprint-btn")
def handle_open_create_sprint(event):
    _open_modal("create-sprint-modal")


@when("click", "#create-task-button")
def handle_open_create_task(event):
    _open_modal("create-task-modal")


@when("click", ".modal-btn-cancel")
def handle_cancel_modal(event):
    modal_id = event.currentTarget.getAttribute("data-modal")
    _close_modal(modal_id)


@when("click", ".modal-overlay")
def handle_backdrop_click(event):
    if event.target.id == event.currentTarget.id:
        _close_modal(event.currentTarget.id)


# --- Form submissions ---
@when("submit", "#create-sprint-form")
def handle_create_sprint_submit(event):
    event.preventDefault()

    name = web.page["sprint-name-input"].value.strip()
    details = web.page["sprint-details-input"].value.strip()
    status = web.page["sprint-status-input"].value

    if not name:
        return

    async def process_create_sprint():
        success, err = await server_data.create_sprint(PROJECT_ID, name, details or "No description", status)
        if success:
            await render_sprints_grid()
            await _refresh_all_card_badges()

    asyncio.ensure_future(process_create_sprint())
    event.currentTarget.reset()
    _close_modal("create-sprint-modal")


@when("submit", "#create-task-form")
def handle_create_task_submit(event):
    event.preventDefault()

    title = web.page["task-title-input"].value.strip()
    tag = web.page["task-tag-input"].value
    priority = web.page["task-priority-input"].value

    if not title:
        return

    async def process_create_task():
        success, err, item = await server_data.create_backlog_item(PROJECT_ID, title, tag, priority)
        if success:
            await render_backlog_list()

    asyncio.ensure_future(process_create_task())
    event.currentTarget.reset()
    _close_modal("create-task-modal")


@when("click", ".sprints-grid")
def handle_sprint_card_click(event):
    if event.target.closest(".burndown-button"):
        return

    card = event.target.closest(".sprint-card")
    if not card:
        return

    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return

    window.location.href = f"sprint-page.html?sprint_id={sprint_id}&project_id={PROJECT_ID}"


async def initialize_dashboard():
    await render_sprints_grid()
    await render_backlog_list()
    await _refresh_all_card_badges()

asyncio.ensure_future(initialize_dashboard())