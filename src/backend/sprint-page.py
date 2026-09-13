import sys
import asyncio

if "." not in sys.path:
    sys.path.append(".")

from pyscript import when, web, document  # type: ignore
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


# NOTE ON DRAG-AND-DROP ARCHITECTURE:
# The raw HTML5 drag events (dragstart/dragover/dragleave/drop) and all the
# purely visual bits (the "dragging"/"drag-over" CSS classes) are handled by
# plain vanilla JS in sprint-page.html, NOT here.
#
# Why: PyScript's @when decorator always defers execution through its own
# internal async dispatcher, regardless of whether your handler is written
# as `def` or `async def`. By the time our Python code runs, the browser has
# already finished dispatching the event and reset event.currentTarget /
# event.dataTransfer to null — accessing them here throws
# "'JsNull' object has no attribute '...'".
#
# So instead, the JS in sprint-page.html reads the dragged card's id and the
# drop target's column key synchronously (while they're still valid), then
# fires a custom "app:card-drop" event carrying only plain strings in
# event.detail. Plain data survives the async handoff fine — only live
# DOM/event object references go stale. This handler does all the actual
# business logic (forward-only rule, moving the card, updating counts).
@when("app:card-drop", "body")
def handle_card_drop(event):
    if sprint_ended:
        return

    detail = event.detail
    card_id = detail.cardId
    target_column = detail.targetColumn

    if not card_id or not target_column:
        return

    # Use document.getElementById here (not web.page[...]) — appendChild
    # needs a real raw DOM Node. web.page[...] returns a Python-side
    # wrapper that works fine for .classList/.getAttribute (those just
    # forward calls) but isn't accepted by appendChild's strict type check,
    # which throws "parameter 1 is not of type 'Node'".
    card = document.getElementById(card_id)
    if not card:
        return

    source_column = card.getAttribute("data-column")

    if source_column == target_column:
        return

    # Enforce forward-only movement across the board.
    if _column_index(target_column) < _column_index(source_column):
        asyncio.ensure_future(
            show_snackbar("Tasks can only be pushed forward on the board.")
        )
        return

    target_body = document.getElementById(f"column-{target_column}")
    if not target_body:
        return

    target_body.appendChild(card)
    card.setAttribute("data-column", target_column)

    _update_column_count(source_column)
    _update_column_count(target_column)


# --- END SPRINT: lock the board ---
# This one never touched event.currentTarget (only web.page[...] lookups by
# id), which is why it worked correctly even before the fix above.
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
