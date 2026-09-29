import json
import time
from pyscript import when, web, window, document  # type: ignore[reportMissingImports]
from constants import DEFAULT_SPRINTS, DEFAULT_BACKLOG_ITEMS

BACKLOG_STORAGE_KEY = "product_backlog_items"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"  # + sprint_id
SPRINTS_STORAGE_KEY = "sprints_list"

_dragged_backlog_id = None


# --- Storage helpers ---
def load_backlog_items():
    raw = window.localStorage.getItem(BACKLOG_STORAGE_KEY)
    if not raw:
        seeded = list(DEFAULT_BACKLOG_ITEMS)
        save_backlog_items(seeded)   # persist immediately so every page sees the same data
        return seeded
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return list(DEFAULT_BACKLOG_ITEMS)


def save_backlog_items(items):
    window.localStorage.setItem(BACKLOG_STORAGE_KEY, json.dumps(items))


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


# --- Rendering the pool sidebar ---
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


def render_backlog_list():
    items = load_backlog_items()
    list_el = web.page["backlog-list"]
    list_el.innerHTML = ""
    for item in items:
        list_el.appendChild(_make_backlog_card(item))
    web.page["count-product-backlog"].textContent = str(len(items))


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
    if _dragged_backlog_id is None:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return

    items = load_backlog_items()
    matching = next((i for i in items if i["id"] == _dragged_backlog_id), None)
    if matching is None:
        return

    remaining = [i for i in items if i["id"] != _dragged_backlog_id]
    save_backlog_items(remaining)
    add_item_to_sprint_backlog(sprint_id, matching)

    dragged_el = web.page[f"backlog-item-{_dragged_backlog_id}"]
    if dragged_el is not None:
        dragged_el.remove()
    web.page["count-product-backlog"].textContent = str(len(remaining))
    _refresh_card_badge(sprint_id)


# --- Sprint storage + rendering ---
def load_sprints():
    raw = window.localStorage.getItem(SPRINTS_STORAGE_KEY)
    if not raw:
        seeded = list(DEFAULT_SPRINTS)
        save_sprints(seeded)   # persist immediately, closes the race condition with sprint-page.py
        return seeded
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return list(DEFAULT_SPRINTS)


def save_sprints(items):
    window.localStorage.setItem(SPRINTS_STORAGE_KEY, json.dumps(items))


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


def render_sprints_grid():
    items = load_sprints()
    grid = document.querySelector(".sprints-grid")
    grid.innerHTML = ""
    for item in items:
        grid.appendChild(_make_sprint_card(item))


def _show_dashboard_view(view_id):
    is_members_view = view_id == "members-view"
    document.querySelector(".sprint-dashboard-layout").classList.toggle("members-open", is_members_view)
    web.page["sprints-view"].classList.toggle("hidden", is_members_view)
    web.page["members-view"].classList.toggle("hidden", not is_members_view)
    web.page["nav-all-projects"].classList.toggle("active", not is_members_view)
    web.page["nav-members"].classList.toggle("active", is_members_view)


@when("click", "#nav-all-projects")
def handle_show_sprints(event):
    _show_dashboard_view("sprints-view")


@when("click", "#nav-members")
def handle_show_members(event):
    _show_dashboard_view("members-view")


# --- Modal open/close ---
def _open_modal(modal_id):
    web.page[modal_id].classList.remove("hidden")


def _close_modal(modal_id):
    web.page[modal_id].classList.add("hidden")


@when("click", ".member-list")
def handle_member_click(event):
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
    _close_modal("member-details-modal")


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

    items = load_sprints()
    new_id = str(int(time.time() * 1000))  # simple unique id
    items.append({"id": new_id, "name": name, "details": details or "No description", "status": status})
    save_sprints(items)

    render_sprints_grid()
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

    items = load_backlog_items()
    new_id = str(int(time.time() * 1000))
    items.append({"id": new_id, "title": title, "tag": tag, "priority": priority})
    save_backlog_items(items)

    render_backlog_list()
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

    window.location.href = f"sprint-page.html?sprint_id={sprint_id}"


render_sprints_grid()
render_backlog_list()
_refresh_all_card_badges()