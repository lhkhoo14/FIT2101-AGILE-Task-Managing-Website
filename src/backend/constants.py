STORAGE_KEY_APP_DATA = "pyscript_app_data"
ACTIVE_SESSION_KEY = "session_user_id"
API_URL = "http://127.0.0.1:8000/api"

DEFAULT_SPRINTS = [
    # No "members" key on the seeded sprints = legacy/open sprint (every user can access it).
    # Sprints created through the UI always store an explicit "members" list.
    {"id": "1", "name": "Sprint 1", "details": "Login & onboarding flow", "status": "active", "priority": "high", "tags": ["auth", "frontend"], "created_at": 1788000000000},
    {"id": "2", "name": "Sprint 2", "details": "Payments integration", "status": "ended", "priority": "medium", "tags": ["payments", "backend"], "created_at": 1788086400000},
    {"id": "3", "name": "Sprint 3", "details": "Reporting dashboard", "status": "active", "priority": "low", "tags": ["reporting", "frontend"], "created_at": 1788172800000},
]

DEFAULT_BACKLOG_ITEMS = [
    {"id": "1", "title": "Add dark mode toggle", "tag": "frontend", "priority": "low"},
    {"id": "2", "title": "Rate-limit login attempts", "tag": "backend", "priority": "high"},
    {"id": "3", "title": "Redesign empty states", "tag": "frontend", "priority": "medium"},
]
DEFAULT_KANBAN_STATES = {
    "1": {
        "backlog": [
            {"id": "task-1", "title": "Design login page wireframe", "tag": "frontend", "priority": "medium", "assignee": "Chee Wei"},
            {"id": "task-2", "title": "Set up Oracle DB schema", "tag": "backend", "priority": "high", "assignee": "Ken Yit"},
        ],
        "active": [
            {"id": "task-3", "title": "Build kanban board UI", "tag": "frontend", "priority": "high", "assignee": "Wei Ho"},
        ],
        "review": [
            {"id": "task-4", "title": "Login form validation logic", "tag": "backend", "priority": "medium", "assignee": "Chee Wei"},
        ],
        "completed": [
            {"id": "task-5", "title": "Set up PyScript project", "tag": "backend", "priority": "low", "assignee": "Lip Hong"},
            {"id": "task-6", "title": "Create ServerData class", "tag": "backend", "priority": "medium", "assignee": "Chee Wei"},
        ],
    },
}