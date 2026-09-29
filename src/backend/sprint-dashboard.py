import sys
import json
import time
import asyncio
from html import escape

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, window, document  # type: ignore[reportMissingImports]
from auth import show_snackbar
from constants import DEFAULT_SPRINTS, DEFAULT_BACKLOG_ITEMS
from models.server_data import ServerData
from sprint_access import (
    is_sprint_member, sort_sprints, normalize_tags, filter_sprints_by_tag,
    PRIORITY_ORDER, DEFAULT_PRIORITY,
)

BACKLOG_STORAGE_KEY = "product_backlog_items"
SPRINT_BACKLOG_KEY_PREFIX = "sprint_backlog_"  # + sprint_id
SPRINTS_STORAGE_KEY = "sprints_list"
FLASH_KEY = "flash_snackbar"  # one-shot message set by other pages (e.g. sprint-page access denied)

_dragged_backlog_id = None

# --- CURRENT USER (sprint membership checks) ---
server_data = ServerData()
_session = server_data.get_active_session()
current_user_id = int(_session) if _session else None


# --- User / member helpers ---
def _display_name(user):
    return user.get("username") or user.get("email") or f"User {user.get('user_id')}"


def _initials(name):
    parts = name.replace("@", " ").replace(".", " ").split()
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _users_by_id():
    return {u["user_id"]: u for u in server_data.users}


def _notify(message):
    asyncio.ensure_future(show_snackbar(message))


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
        if card.getAttribute("data-member") == "true":
            card.classList.add("card-drop-target")
        else:
            card.classList.add("card-drop-denied")


@when("dragleave", ".sprints-grid")
def handle_card_drag_leave(event):
    card = event.target.closest(".sprint-card")
    if card:
        card.classList.remove("card-drop-target")
        card.classList.remove("card-drop-denied")


@when("drop", ".sprints-grid")
def handle_card_drop(event):
    event.preventDefault()
    card = event.target.closest(".sprint-card")
    if not card:
        return
    card.classList.remove("card-drop-target")
    card.classList.remove("card-drop-denied")
    if _dragged_backlog_id is None:
        return
    sprint_id = card.getAttribute("data-sprint-id")
    if not sprint_id:
        return

    # Only assigned members may drop tasks into a sprint. Checked against
    # storage (not the card's data attribute) so it can't be bypassed via the DOM.
    sprint = next((s for s in load_sprints() if s["id"] == sprint_id), None)
    if sprint is None or not is_sprint_member(sprint, current_user_id):
        _notify("You are not assigned to this sprint, so you can't add tasks to it.")
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
        f'<span class="member-avatar" title="{escape(n)}">{escape(_initials(n))}</span>'
        for n in names[:4]
    )
    extra = len(names) - 4
    if extra > 0:
        html += f'<span class="member-avatar member-avatar-more" title="{extra} more">+{extra}</span>'
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


def render_sprints_grid():
    sort_select = web.page["sort-select"]
    sort_key = sort_select.value if sort_select is not None else "date"
    search_input = web.page["global-search"]
    query = search_input.value.strip() if search_input is not None else ""

    all_items = load_sprints()
    items = sort_sprints(filter_sprints_by_tag(all_items, query), sort_key)
    users = _users_by_id()
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


# --- Modal open/close ---
def _open_modal(modal_id):
    web.page[modal_id].classList.remove("hidden")


def _close_modal(modal_id):
    web.page[modal_id].classList.add("hidden")


def _render_member_options():
    """Fill the create-sprint modal with one checkbox per registered user."""
    server_data.load_data()  # pick up users who signed up since this page loaded
    container = web.page["sprint-members-list"]
    container.innerHTML = ""

    for user in server_data.users:
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

    if len(server_data.users) <= 1:
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


@when("click", "#create-sprint-btn")
def handle_open_create_sprint(event):
    _render_member_options()
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
    priority = web.page["sprint-priority-input"].value
    if priority not in PRIORITY_ORDER:
        priority = DEFAULT_PRIORITY

    if not name:
        return

    items = load_sprints()
    now_ms = int(time.time() * 1000)
    items.append({
        "id": str(now_ms),  # simple unique id
        "name": name,
        "details": details or "No description",
        "status": "active",  # new sprints always start active; "End Sprint" on the sprint page closes them
        "priority": priority,
        "tags": normalize_tags(web.page["sprint-tags-input"].value),
        "members": _selected_member_ids(),
        "created_by": current_user_id,
        "created_at": now_ms,
    })
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

    sprint = next((s for s in load_sprints() if s["id"] == sprint_id), None)
    if sprint is None or not is_sprint_member(sprint, current_user_id):
        _notify("You are not assigned to this sprint.")
        return

    window.location.href = f"sprint-page.html?sprint_id={sprint_id}"


render_sprints_grid()
render_backlog_list()
_refresh_all_card_badges()

# One-shot message left by another page (e.g. redirected from a sprint you're not assigned to)
_flash = window.sessionStorage.getItem(FLASH_KEY)
if _flash:
    window.sessionStorage.removeItem(FLASH_KEY)
    _notify(_flash)