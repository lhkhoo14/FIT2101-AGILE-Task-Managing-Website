from pyscript import when, window  # type: ignore
from models.server_data import ServerData

# 1. Instantiate database manager
server_data = ServerData()

def guard_session() -> str | None:
    """Validates session and boots to login if invalid."""
    session_id = server_data.get_active_session()

    if session_id is None or server_data.find_user_by_id(int(session_id)) is None:
        print("[Auth Guard] Invalid session. Redirecting to login...")
        server_data.clear_session()
        window.location.replace("login.html")
        return None

    return session_id

# 2. Enforce guard immediately
current_session_id = guard_session()

if current_session_id:
    # Get active user
    current_user = server_data.find_user_by_id(int(current_session_id))
    if current_user is not None:
        print(f"Authenticated as: {current_user.username}")

    # 3. Import layout handlers (sidebar toggle, signout, profile menu)
    import layout  # Binds global layout event listeners

    # 4. Initialize dashboard-specific UI & data
    # e.g., render_projects_grid(server_data.projects)
    # e.g., update_profile_header(current_user)

@when("click", ".projects-grid")
def handle_project_card_click(event):
    card = event.target.closest(".project-card")
    if not card:
        return

    window.location.href = "sprint-dashboard.html"