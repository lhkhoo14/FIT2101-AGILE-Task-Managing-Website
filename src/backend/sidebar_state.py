"""Shared navigation-rail collapse preference (US-17).

The project column bar has to stay expanded unless the user collapses it, and
that choice has to survive moving between the project views. One module owns the
storage and the markup sync so the toolbar button behaves identically on every
page that shows a rail.

The preference lives in sessionStorage rather than localStorage because US-17
scopes it to the active browser session.
"""
from pyscript import document, window  # type: ignore

# US-17: the preference must outlive a route change but not the browser session.
STORAGE_KEY = "nav_rail_collapsed"

# The toolbar button controls the leftmost rail on the page: the project column
# bar when the page has one, otherwise the dashboard/projects rail.
_PROJECT_RAIL = "#project-sidebar"
_DASHBOARD_RAIL = "#sidebar"
_TOGGLE_BUTTON = "#toggle-sidebar-btn"


def rail():
    """The rail the toolbar button controls, or None when this page has none."""
    return document.querySelector(_PROJECT_RAIL) or document.querySelector(_DASHBOARD_RAIL)


def is_collapsed(sidebar=None):
    sidebar = sidebar if sidebar is not None else rail()
    return sidebar is not None and "collapsed" in sidebar.classList


def set_collapsed(collapsed, sidebar=None, remember=True):
    """Apply a collapse state to the rail and (by default) persist the choice."""
    sidebar = sidebar if sidebar is not None else rail()
    if sidebar is None:
        return False

    if collapsed:
        sidebar.classList.add("collapsed")
    else:
        sidebar.classList.remove("collapsed")

    if remember:
        _remember(collapsed)
    _sync_button(collapsed)
    return collapsed


def toggle(sidebar=None):
    """Flip the rail. Called by the toolbar button on every layout."""
    sidebar = sidebar if sidebar is not None else rail()
    return set_collapsed(not is_collapsed(sidebar), sidebar)


def restore():
    """Re-apply the stored preference to this page's rail.

    US-17: without this, each page load looked like the navigation had reset
    itself. Returns the state that was applied.
    """
    sidebar = rail()
    if sidebar is None:
        return False

    collapsed = _stored()
    if collapsed:
        sidebar.classList.add("collapsed")
    else:
        sidebar.classList.remove("collapsed")
    _sync_button(collapsed)
    return collapsed


def _stored():
    try:
        return window.sessionStorage.getItem(STORAGE_KEY) == "1"
    except Exception as exc:
        print(f"[Sidebar] Could not read the collapse preference: {exc}")
        return False


def _remember(collapsed):
    try:
        window.sessionStorage.setItem(STORAGE_KEY, "1" if collapsed else "0")
    except Exception as exc:
        print(f"[Sidebar] Could not store the collapse preference: {exc}")


def _sync_button(collapsed):
    """Keep the toolbar button's label and aria state in step with the rail."""
    button = document.querySelector(_TOGGLE_BUTTON)
    if button is None:
        return
    label = "Expand navigation" if collapsed else "Collapse navigation"
    button.setAttribute("aria-expanded", "false" if collapsed else "true")
    button.setAttribute("title", label)
    button.setAttribute("aria-label", label)
