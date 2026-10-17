import js # type: ignore
from pyscript import window # type: ignore

def get_project_id_from_url() -> int | None:
    params = js.URLSearchParams.new(window.location.search)
    project_id = params.get("project_id")
    if project_id and project_id.isdigit():
        return int(project_id)
    return None