import html
from typing import Optional

import pytest

from helpers import load_functions
import frontend_paths

SRC = frontend_paths.UTILS / "project_role_helpers.py"
ns = load_functions(
    SRC,
    [
        "ROLE_PERMISSIONS", "PRESET_ROLES", "PROTECTED_PRESET_NAMES", "PRESET_RANK",
        "SINGLETON_PRESET_ROLES", "UNRANKED",
        "build_permissions_checklist_html", "permissions_for_user",
        "highest_preset_rank", "member_permission_sets", "can_remove_member",
        "build_conflicts_checklist_html",
    ],
    Optional=Optional, html=html,
)

permissions_for_user = ns["permissions_for_user"]
highest_preset_rank = ns["highest_preset_rank"]
member_permission_sets = ns["member_permission_sets"]
can_remove_member = ns["can_remove_member"]
build_permissions_checklist_html = ns["build_permissions_checklist_html"]
build_conflicts_checklist_html = ns["build_conflicts_checklist_html"]


def _project():
    return {
        "roles": {
            "Project Creator": [1],
            "Scrum Master": [2],
            "Employee": [3, 4],
            "Reviewer": [5],          # a custom role
        },
        "role_definitions": {
            "Project Creator": {"permissions": ["manage_members", "manage_sprints", "review_tasks"]},
            "Scrum Master": {"permissions": ["manage_sprints", "review_tasks"]},
            "Employee": {"permissions": ["edit_sprints"]},
            "Reviewer": {"permissions": ["review_tasks"]},
        },
    }


@pytest.mark.unit
def test_permissions_for_user_combines_roles():
    project = _project()
    project["roles"]["Employee"].append(5)   # 5 now holds Employee and Reviewer
    assert permissions_for_user(project, 5) == {"edit_sprints", "review_tasks"}


@pytest.mark.unit
def test_permissions_for_user_accepts_string_ids_and_custom_roles():
    assert permissions_for_user(_project(), "5") == {"review_tasks"}


@pytest.mark.unit
def test_permissions_for_user_empty_for_unknown_user_or_missing_data():
    assert permissions_for_user(_project(), 99) == set()
    assert permissions_for_user(None, 1) == set()
    assert permissions_for_user(_project(), None) == set()
    assert permissions_for_user({"roles": {"X": "not-a-list"}}, 1) == set()


@pytest.mark.unit
def test_permissions_for_user_ignores_role_without_definition():
    project = {"roles": {"Ghost": [1]}, "role_definitions": {}}
    assert permissions_for_user(project, 1) == set()


@pytest.mark.unit
def test_highest_preset_rank():
    project = _project()
    assert highest_preset_rank(project, 1) == 5
    assert highest_preset_rank(project, 2) == 4
    assert highest_preset_rank(project, 3) == 2
    assert highest_preset_rank(project, 5) == ns["UNRANKED"]   # custom role only
    assert highest_preset_rank(project, 99) == ns["UNRANKED"]
    assert highest_preset_rank(None, 1) == ns["UNRANKED"]


@pytest.mark.unit
def test_member_permission_sets_lists_every_role_holder():
    sets = member_permission_sets(_project())
    assert set(sets) == {"1", "2", "3", "4", "5"}
    assert sets["3"] == {"edit_sprints"}
    assert member_permission_sets(None) == {}


@pytest.mark.unit
def test_can_remove_member_rules():
    project = _project()
    assert can_remove_member(project, 1, 2)       # creator outranks scrum master
    assert can_remove_member(project, 2, 3)       # scrum master outranks employee
    assert not can_remove_member(project, 3, 2)   # employee cannot remove up
    assert not can_remove_member(project, 1, 1)   # never yourself
    assert not can_remove_member(project, None, 1)
    assert not can_remove_member(project, 1, None)


@pytest.mark.unit
def test_can_remove_member_equal_rank_needs_strictly_more_permissions():
    project = _project()
    project["roles"]["Employee"] = [3, 4]
    project["roles"]["Extra"] = [3]
    project["role_definitions"]["Extra"] = {"permissions": ["review_tasks"]}
    assert can_remove_member(project, 3, 4)       # 3 holds more than 4
    assert not can_remove_member(project, 4, 3)
    assert not can_remove_member(project, 3, 3)


@pytest.mark.unit
def test_can_remove_member_custom_role_cannot_remove_stronger_member():
    project = _project()
    project["roles"]["Power"] = [6]
    project["role_definitions"]["Power"] = {
        "permissions": ["manage_members", "manage_sprints", "review_tasks", "edit_sprints"]}
    # 5 (custom, rank 1) vs 6 (custom, rank 1): the bigger set wins
    assert can_remove_member(project, 6, 5)
    assert not can_remove_member(project, 5, 6)


@pytest.mark.unit
def test_build_permissions_checklist_html_marks_current_and_all_options():
    perms = {"manage_sprints": "Create sprints", "review_tasks": "Review <tasks>"}
    out = build_permissions_checklist_html(perms, ["review_tasks"])
    assert out.count("<input") == 2
    assert out.count("checked") == 1
    assert "Review &lt;tasks&gt;" in out or "Review <tasks>" in out
    none_checked = build_permissions_checklist_html(perms, None)
    assert "checked" not in none_checked


@pytest.mark.unit
def test_build_conflicts_checklist_html_skips_self_and_escapes():
    roles = [{"name": "A"}, {"name": "B<script>"}, {"name": "C"}]
    out = build_conflicts_checklist_html(roles, "A", ["C"])
    assert 'value="A"' not in out
    assert "B&lt;script&gt;" in out and "<script>" not in out
    assert out.count("checked") == 1
    assert build_conflicts_checklist_html([], None, None) == ""


@pytest.mark.unit
def test_preset_roles_are_consistent():
    presets, rank = ns["PRESET_ROLES"], ns["PRESET_RANK"]
    assert ns["PROTECTED_PRESET_NAMES"] == set(presets)
    for name in ns["SINGLETON_PRESET_ROLES"]:
        assert name in presets
    for definition in presets.values():
        assert set(definition["permissions"]) <= set(ns["ROLE_PERMISSIONS"])
    assert rank["Project Creator"] > rank["Scrum Master"] >= rank["Product Owner"] > rank["Employee"]