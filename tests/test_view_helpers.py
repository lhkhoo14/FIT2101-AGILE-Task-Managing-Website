import pytest

from helpers import load_functions
import frontend_paths
import charts
from project_role_helpers import PRESET_RANK, UNRANKED

dash = load_functions(
    frontend_paths.VIEWS / "sprint-dashboard.py",
    ["_display_name", "_initials", "_date_range_text"],
    charts=charts,
)
members = load_functions(
    frontend_paths.VIEWS / "project_members.py",
    ["get_role_for_member", "role_sort_key"],
    PRESET_RANK=PRESET_RANK,
    UNRANKED=UNRANKED,
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
def test_role_for_member_picks_the_most_senior_role():
    roles = {"Scrum Master": [1], "Employee": [2], "Project Creator": [2], "Manager": []}
    get_role = members["get_role_for_member"]
    assert get_role(1, roles) == "Scrum Master"
    assert get_role(2, roles) == "Project Creator"     # holds two roles: the senior one wins
    assert get_role("1", roles) == "Scrum Master"      # ids compare as text
    assert get_role(3, roles) is None                  # no role at all


@pytest.mark.unit
def test_members_are_sorted_most_senior_first():
    key = members["role_sort_key"]
    roles = ["Employee", None, "Scrum Master", "Project Creator", "Manager"]
    assert sorted(roles, key=key) == ["Project Creator", "Scrum Master", "Manager", "Employee", None]