import pytest

from helpers import load_functions
import frontend_paths
import charts

dash = load_functions(
    frontend_paths.VIEWS / "sprint-dashboard.py",
    ["_display_name", "_initials", "_date_range_text"],
    charts=charts,
)
members = load_functions(
    frontend_paths.VIEWS / "project_members.py",
    ["get_role_for_member", "get_role_priority"],
)


@pytest.mark.unit
def test_display_name_prefers_username_then_email_then_id():
    assert dash["_display_name"]({"username": "ann", "email": "a@x.com", "user_id": 1}) == "ann"
    assert dash["_display_name"]({"email": "a@x.com", "user_id": 1}) == "a@x.com"
    assert dash["_display_name"]({"user_id": 9}) == "User 9"


@pytest.mark.unit
def test_initials():
    assert dash["_initials"]("Ann Lee") == "AL"
    assert dash["_initials"]("ann.lee@mail.com") == "AL"
    assert dash["_initials"]("zed") == "Z"
    assert dash["_initials"]("") == "?"
    assert dash["_initials"]("a b c d") == "AB"


@pytest.mark.unit
def test_date_range_text():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-14"}
    assert dash["_date_range_text"](sprint) == "Oct 1 – Oct 14, 2026"
    assert dash["_date_range_text"]({"start_date": "2026-10-01"}) == ""
    assert dash["_date_range_text"]({}) == ""


@pytest.mark.unit
def test_role_for_member_and_priority_ordering():
    roles = {"Scrum Master": [1], "Employee": [2]}
    assert members["get_role_for_member"](1, roles) == "Scrum Master"
    assert members["get_role_for_member"](3, roles) == "Member"
    prio = members["get_role_priority"]
    assert prio("Product Owner") == prio("Scrum Master") == 0
    assert prio("Member") == 1
    assert prio("Employee") == 2
    assert sorted(["Employee", "Member", "Scrum Master"], key=prio) == ["Scrum Master", "Member", "Employee"]