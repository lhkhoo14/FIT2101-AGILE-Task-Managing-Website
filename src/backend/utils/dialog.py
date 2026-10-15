"""
One shared confirmation dialog for irreversible actions.

Every deletion in the app - project, sprint, task, member, account - asks the
same question through this module, instead of each page carrying its own modal
markup and its own wording. The dialog builds itself on first use, with inline
styles, so it also works on pages that do not load a modal stylesheet, and it
waits on an asyncio Future so a caller reads like:

    confirmed, _ = await confirm_action()
    if not confirmed:
        return
"""
import asyncio
import sys

if "." not in sys.path:
    sys.path.append(".")

from pyscript import document  # type: ignore
from pyodide.ffi import create_proxy  # type: ignore

CANNOT_BE_REVERSED = "Are you sure? This action cannot be reversed!"

_STYLES = """
#confirm-dialog-overlay {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.55);
  display: flex; align-items: center; justify-content: center; z-index: 2000;
}
#confirm-dialog-overlay.hidden { display: none; }
#confirm-dialog-box {
  background: #fff; border-radius: 12px; padding: 24px; width: min(420px, 90vw);
  box-shadow: 0 20px 45px rgba(15, 23, 42, 0.3);
}
#confirm-dialog-title { margin: 0 0 8px; font-size: 16px; color: #0f172a; }
#confirm-dialog-message { margin: 0 0 18px; font-size: 13px; color: #475569; line-height: 1.5; }
#confirm-dialog-password {
  width: 100%; box-sizing: border-box; padding: 9px 10px; margin-bottom: 16px;
  border: 1px solid #cbd5e1; border-radius: 8px; font-size: 13px;
}
#confirm-dialog-actions { display: flex; justify-content: flex-end; gap: 10px; }
#confirm-dialog-actions button {
  padding: 9px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer;
}
#confirm-dialog-no { background: #f1f5f9; color: #334155; border: 1px solid #cbd5e1; }
#confirm-dialog-yes { background: #dc2626; color: #fff; border: 1px solid #dc2626; }
"""

_mounted = False


def _element(element_id: str):
    return document.getElementById(element_id)


def _mount() -> None:
    """Add the dialog to the page once, whatever page it is being asked from."""
    global _mounted
    if _mounted:
        return

    style = document.createElement("style")
    style.textContent = _STYLES
    document.head.appendChild(style)

    overlay = document.createElement("div")
    overlay.id = "confirm-dialog-overlay"
    overlay.className = "hidden"
    overlay.innerHTML = (
        '<div id="confirm-dialog-box" role="dialog" aria-modal="true">'
        '<h3 id="confirm-dialog-title"></h3>'
        '<p id="confirm-dialog-message"></p>'
        '<input id="confirm-dialog-password" type="password" class="hidden"'
        ' placeholder="Your password" autocomplete="current-password">'
        '<div id="confirm-dialog-actions">'
        '<button id="confirm-dialog-no" type="button">No</button>'
        '<button id="confirm-dialog-yes" type="button">Yes</button>'
        "</div></div>"
    )
    document.body.appendChild(overlay)
    _mounted = True


async def confirm_action(message: str = CANNOT_BE_REVERSED, *,
                         title: str = "Delete",
                         require_password: bool = False) -> tuple[bool, str]:
    """Ask the user to confirm something that cannot be undone.

    Returns (confirmed, password). The password is only collected when
    require_password is set - used by account deletion, where typing it is what
    proves the person at the keyboard owns the account - and is empty otherwise.
    """
    _mount()
    overlay = _element("confirm-dialog-overlay")
    _element("confirm-dialog-title").textContent = title
    _element("confirm-dialog-message").textContent = message

    password_field = _element("confirm-dialog-password")
    password_field.value = ""
    if require_password:
        password_field.classList.remove("hidden")
    else:
        password_field.classList.add("hidden")

    answer: asyncio.Future = asyncio.get_running_loop().create_future()

    def settle(confirmed: bool) -> None:
        if not answer.done():
            answer.set_result(confirmed)

    def on_yes(event):
        settle(True)

    def on_no(event):
        settle(False)

    def on_key(event):
        # Escape is a "No": the safe answer for a dialog that ends in deletion.
        if event.key == "Escape":
            settle(False)

    yes_button = _element("confirm-dialog-yes")
    no_button = _element("confirm-dialog-no")
    proxies = [create_proxy(on_yes), create_proxy(on_no), create_proxy(on_key)]
    yes_button.addEventListener("click", proxies[0])
    no_button.addEventListener("click", proxies[1])
    document.addEventListener("keydown", proxies[2])

    overlay.classList.remove("hidden")
    if require_password:
        password_field.focus()

    try:
        confirmed = await answer
    finally:
        overlay.classList.add("hidden")
        yes_button.removeEventListener("click", proxies[0])
        no_button.removeEventListener("click", proxies[1])
        document.removeEventListener("keydown", proxies[2])
        for proxy in proxies:
            proxy.destroy()

    return bool(confirmed), password_field.value
