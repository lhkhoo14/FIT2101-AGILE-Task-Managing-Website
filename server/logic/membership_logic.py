"""
Pure membership logic for taking a user out of a project.

Deletion has to touch every place that names a member: the project's member and
contributor lists, its role assignments, each sprint's member list and the
assignees on each task board. Keeping that cascade here, with no FastAPI
imports, means the remove-member route and the account-deletion route share one
implementation of it, and it can be unit-tested on its own.
"""
from typing import Any, Dict, List

from logic.contribution_logic import COLUMNS, as_id, member_ids


# ---------------------------------------------------------------------------
# Who may remove whom
# ---------------------------------------------------------------------------
# Preset roles by authority. Custom roles have no rank of their own and are
# compared by the permissions they grant instead (see can_remove_member). This
# mirrors PRESET_RANK in src/backend/utils/project_role_helpers.py, so the
# Members page only offers Remove on the members this route will accept.
PRESET_RANK = {
    "Project Creator": 5,
    "Scrum Master": 4,
    "Product Owner": 4,
    "Manager": 3,
    "Employee": 2,
}

# A member holding only custom roles, or no role at all, ranks below every preset.
UNRANKED = 1


def permissions_for(project: Dict[str, Any], user_id: Any) -> set:
    """The permissions a user holds in a project, gathered from their roles."""
    target = as_id(user_id)
    if target is None:
        return set()

    roles = project.get("roles") or {}
    definitions = project.get("role_definitions") or {}
    granted = set()
    for role_name, holders in roles.items():
        if not isinstance(holders, list):
            continue
        if target not in {as_id(holder) for holder in holders}:
            continue
        meta = definitions.get(role_name)
        permissions = meta.get("permissions") if isinstance(meta, dict) else None
        if isinstance(permissions, list):
            granted.update(permissions)
    return granted


def highest_preset_rank(project: Dict[str, Any], user_id: Any) -> int:
    """The rank of the member's most senior preset role (UNRANKED if they hold none)."""
    target = as_id(user_id)
    if target is None:
        return UNRANKED

    roles = project.get("roles") or {}
    best = UNRANKED
    for role_name, holders in roles.items():
        if not isinstance(holders, list):
            continue
        if target not in {as_id(holder) for holder in holders}:
            continue
        best = max(best, PRESET_RANK.get(role_name, UNRANKED))
    return best


def can_remove_member(project: Dict[str, Any], actor_id: Any, target_id: Any) -> bool:
    """Whether actor_id outranks target_id enough to take them out of the project.

    The rule the Members page uses, enforced here as well so the API cannot be
    used to skip it: preset rank decides first (Project Creator > Scrum Master =
    Product Owner > Manager > Employee, with custom-role-only and role-less
    members below all of them), and when two members rank the same the one whose
    permission set is the strict subset can be removed - which is how custom
    roles, the only roles with no rank, are compared, and what stops a custom
    role being removed by somebody it out-permissions.

    Nobody may remove themselves: a member who wants out uses their account page.
    """
    actor = as_id(actor_id)
    target = as_id(target_id)
    if actor is None or target is None or actor == target:
        return False

    actor_rank = highest_preset_rank(project, actor)
    target_rank = highest_preset_rank(project, target)
    if target_rank > actor_rank:
        return False

    actor_permissions = permissions_for(project, actor)
    target_permissions = permissions_for(project, target)
    if target_rank == actor_rank:
        return target_permissions < actor_permissions
    return not (actor_permissions < target_permissions)


def creator_ids(project: Dict[str, Any]) -> List[int]:
    """User ids holding the Project Creator role, falling back to `creator`."""
    roles = project.get("roles") or {}
    raw = roles.get("Project Creator")
    if not isinstance(raw, list):
        raw = project.get("creator", []) or []
    ids: List[int] = []
    for value in raw:
        parsed = as_id(value)
        if parsed is not None and parsed not in ids:
            ids.append(parsed)
    return ids


def is_sole_creator(project: Dict[str, Any], user_id: Any) -> bool:
    """True when this user is the project's only Project Creator."""
    target = as_id(user_id)
    return target is not None and creator_ids(project) == [target]


def sole_creator_projects(projects: Any, user_id: Any) -> List[Dict[str, Any]]:
    """Projects that would be left without an owner if this user were removed.

    Only projects the user is still a member of are reported. One they have
    already been removed from cannot be handed over by them anyway, so refusing
    the account deletion for it would lock that account in place for good.
    """
    return [
        project
        for project in projects or []
        if is_sole_creator(project, user_id) and as_id(user_id) in set(member_ids(project))
    ]


def unassign_tasks(state: Dict[str, Any], user_id: int) -> bool:
    """Clear the assignee of every task on one board assigned to this user."""
    changed = False
    for column in COLUMNS:
        for task in (state or {}).get(column, []) or []:
            if as_id(task.get("assignee_id")) != user_id:
                continue
            task["assignee_id"] = None
            task["assignee"] = None
            changed = True
    return changed


def detach_member(project: Dict[str, Any], user_id: Any) -> bool:
    """Remove every trace of one member from one project, keeping their work.

    Membership, contributor status, role assignments, sprint membership and task
    assignments are all cleared. The tasks themselves stay on their boards,
    unassigned, because removing a person is not the same as removing what they
    built. Returns True when something actually changed.
    """
    target = as_id(user_id)
    if target is None:
        return False

    changed = False

    for field in ("members", "contribute"):
        values = project.get(field)
        if not isinstance(values, list):
            continue
        kept = [value for value in values if as_id(value) != target]
        if len(kept) != len(values):
            project[field] = kept
            changed = True

    roles = project.get("roles")
    if isinstance(roles, dict):
        # Only existing keys are reassigned, never added or removed, so the
        # iteration below cannot invalidate itself.
        for role_name, holders in roles.items():
            if not isinstance(holders, list):
                continue
            kept = [value for value in holders if as_id(value) != target]
            if len(kept) != len(holders):
                roles[role_name] = kept
                changed = True

    for sprint in project.get("sprints", []) or []:
        members = sprint.get("members")
        if isinstance(members, list):
            kept = [value for value in members if as_id(value) != target]
            if len(kept) != len(members):
                sprint["members"] = kept
                changed = True
        if unassign_tasks(sprint.get("kanban_state") or {}, target):
            changed = True

    return changed
