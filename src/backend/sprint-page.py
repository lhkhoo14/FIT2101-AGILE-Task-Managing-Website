import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web  # type: ignore
from auth import show_snackbar

# Columns in left-to-right (forward) order.
# Matches the "tasks can only move forward" rule from the project plan.
COLUMN_ORDER = ["backlog", "active", "review", "completed"]

# Frontend-only flag for now — once the sprint is "ended" the board locks.
# Will eventually be replaced by a real status flag read from ServerData.
sprint_ended = False


def _column_index(column_key: str) -> int:
    return COLUMN_ORDER.index(column_key)


def _update_column_count(column_key: str):
    body = web.page[f"column-{column_key}"]
    count_el = web.page[f"count-{column_key}"]
    if body is not None and count_el is not None:
        count_el.textContent = str(len(body.children))


def _refresh_all_counts():
    for key in COLUMN_ORDER:
        _update_column_count(key)


# --- DRAG START: remember which card is being moved ---
@when("dragstart", ".task-card")
def handle_drag_start(event):
    if sprint_ended:
        event.preventDefault()
        return

    card = event.currentTarget
    event.dataTransfer.setData("text/plain", card.id)
    event.dataTransfer.effectAllowed = "move"
    card.classList.add("dragging")


@when("dragend", ".task-card")
def handle_drag_end(event):
    event.currentTarget.classList.remove("dragging")


# --- DRAG OVER A COLUMN: allow the drop + highlight the column ---
@when("dragover", ".kanban-column-body")
def handle_drag_over(event):
    if sprint_ended:
        return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    event.currentTarget.classList.add("drag-over")


@when("dragleave", ".kanban-column-body")
def handle_drag_leave(event):
    event.currentTarget.classList.remove("drag-over")


# --- DROP: move the card, but only forward ---
# NOTE: this must stay a plain (non-async) function. event.currentTarget is
# only valid while the event is still dispatching — an `async def` handler
# lets the browser finish dispatch (nulling currentTarget) before our code
# runs, which throws "'JsNull' object has no attribute 'classList'".
@when("drop", ".kanban-column-body")
def handle_drop(event):
    event.preventDefault()
    target_body = event.currentTarget
    target_body.classList.remove("drag-over")

    if sprint_ended:
        return

    card_id = event.dataTransfer.getData("text/plain")
    card = web.page[card_id]
    if card is None:
        return

    source_column = card.getAttribute("data-column")
    target_column = target_body.getAttribute("data-column")

    if source_column == target_column:
        return

    # Enforce forward-only movement across the board.
    if _column_index(target_column) < _column_index(source_column):
        # Fire-and-forget: don't await inside a sync handler, and don't make
        # this handler async (see note above).
        asyncio.ensure_future(
            show_snackbar("Tasks can only be pushed forward on the board.")
        )
        return

    target_body.appendChild(card)
    card.setAttribute("data-column", target_column)

    _update_column_count(source_column)
    _update_column_count(target_column)


# --- END SPRINT: lock the board ---
# Kept synchronous for the same reason as handle_drop, above.
@when("click", "#end-sprint-btn")
def handle_end_sprint(event):
    global sprint_ended
    sprint_ended = True

    board = web.page["kanban-board"]
    if board is not None:
        board.classList.add("sprint-ended")

    end_btn = web.page["end-sprint-btn"]
    if end_btn is not None:
        end_btn.textContent = "Sprint Ended"
        end_btn.disabled = True

    asyncio.ensure_future(show_snackbar("Sprint ended. Board is now locked."))


_refresh_all_counts()