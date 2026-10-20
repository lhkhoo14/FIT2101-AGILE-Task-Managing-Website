import pytest

import frontend_paths  # noqa: F401  (puts src/backend on sys.path)
from sprint_access import (
    is_sprint_member, leadership_role_for, sprint_created_at, sort_sprints,
    normalize_tags, tags_match_query, filter_sprints_by_tag, task_tags,
    task_matches_tag_query, MAX_TAGS, MAX_TAG_LENGTH,
)


# ---- membership -----------------------------------------------------------
@pytest.mark.unit
def test_legacy_sprint_without_members_is_open_to_everyone():
    assert is_sprint_member({"name": "old"}, 5) is True


@pytest.mark.unit
def test_sprint_with_members_only_admits_listed_users():
    sprint = {"members": [1, "2"]}
    assert is_sprint_member(sprint, 1)
    assert is_sprint_member(sprint, 2)
    assert not is_sprint_member(sprint, 3)


@pytest.mark.unit
def test_empty_members_list_is_restricted_not_open():
    assert is_sprint_member({"members": []}, 1) is False


@pytest.mark.unit
def test_non_numeric_user_id_is_rejected():
    assert is_sprint_member({"members": [1]}, "abc") is False
    assert is_sprint_member({"members": [1]}, None) is False


# ---- leadership -----------------------------------------------------------
@pytest.mark.unit
def test_leadership_role_found_for_holder():
    payload = {"roles": {"Scrum Master": [7], "Employee": [8]}}
    assert leadership_role_for(payload, 7) == "Scrum Master"
    assert leadership_role_for(payload, "7") == "Scrum Master"


@pytest.mark.unit
def test_leadership_role_none_for_non_leader_or_missing_payload():
    payload = {"roles": {"Scrum Master": [7], "Employee": [8]}}
    assert leadership_role_for(payload, 8) is None
    assert leadership_role_for(None, 1) is None
    assert leadership_role_for({}, 1) is None


@pytest.mark.unit
def test_leadership_role_priority_is_creator_first():
    payload = {"roles": {"Product Owner": [1], "Project Creator": [1]}}
    assert leadership_role_for(payload, 1) == "Project Creator"


# ---- sprint creation time & sorting --------------------------------------
@pytest.mark.unit
def test_sprint_created_at_prefers_field_then_id_then_zero():
    assert sprint_created_at({"created_at": 123}) == 123
    assert sprint_created_at({"id": "1700000000000"}) == 1700000000000
    assert sprint_created_at({"id": "5"}) == 0
    assert sprint_created_at({"created_at": "bad"}) == 0
    assert sprint_created_at({}) == 0


@pytest.mark.unit
def test_sort_sprints_by_date_priority_and_name():
    a = {"name": "banana", "priority": "low", "created_at": 1}
    b = {"name": "Apple", "priority": "high", "created_at": 3}
    c = {"name": "cherry", "priority": "medium", "created_at": 2}
    sprints = [a, b, c]
    assert sort_sprints(sprints, "date") == [b, c, a]
    assert sort_sprints(sprints, "priority") == [b, c, a]
    assert sort_sprints(sprints, "name") == [b, a, c]
    # The input list is left untouched.
    assert sprints == [a, b, c]


@pytest.mark.unit
def test_sort_sprints_unknown_priority_counts_as_medium():
    odd = {"name": "x", "priority": "urgent"}
    low = {"name": "y", "priority": "low"}
    high = {"name": "z", "priority": "high"}
    assert sort_sprints([low, odd, high], "priority") == [high, odd, low]


# ---- tags -----------------------------------------------------------------
@pytest.mark.unit
def test_normalize_tags_cleans_input():
    assert normalize_tags("Frontend, #API ,, urgent, api") == ["frontend", "api", "urgent"]
    assert normalize_tags(["  Big   Tag ", "#X"]) == ["big tag", "x"]
    assert normalize_tags(None) == []
    assert normalize_tags("") == []


@pytest.mark.unit
def test_normalize_tags_enforces_limits():
    long_tag = "a" * (MAX_TAG_LENGTH + 10)
    assert normalize_tags(long_tag) == ["a" * MAX_TAG_LENGTH]
    many = ",".join(f"t{i}" for i in range(MAX_TAGS + 5))
    assert len(normalize_tags(many)) == MAX_TAGS


@pytest.mark.unit
def test_tags_match_query_rules():
    tags = ["frontend", "api"]
    assert tags_match_query(tags, "")            # empty search matches all
    assert tags_match_query(tags, "front")       # partial match
    assert tags_match_query(tags, "#api, front") # every term must match something
    assert not tags_match_query(tags, "backend")
    assert not tags_match_query([], "front")     # untagged never matches a search
    assert tags_match_query([], "")


@pytest.mark.unit
def test_filter_sprints_by_tag():
    sprints = [{"name": "a", "tags": ["ui"]}, {"name": "b", "tags": ["db"]}, {"name": "c"}]
    assert filter_sprints_by_tag(sprints, "ui") == [sprints[0]]
    assert filter_sprints_by_tag(sprints, "") == sprints


@pytest.mark.unit
def test_task_tags_reads_tags_list_or_legacy_single_tag():
    assert task_tags({"tags": ["A", "b"]}) == ["a", "b"]
    assert task_tags({"tag": "Legacy"}) == ["legacy"]
    assert task_tags({}) == []


@pytest.mark.unit
def test_task_matches_tag_query():
    task = {"tags": ["design"]}
    assert task_matches_tag_query(task, "des")
    assert not task_matches_tag_query(task, "dev")
    assert task_matches_tag_query({}, "")