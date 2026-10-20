import html
from datetime import datetime, timezone

import pytest

from helpers import load_functions
import frontend_paths
from sprint_access import task_tags, task_matches_tag_query

COLUMN_ORDER = ["backlog", "active", "review", "completed"]

ns = load_functions(
    frontend_paths.VIEWS / "sprint-page.py",
    ["_as_id", "_normalized_task_id", "_tag_chips_html", "_task_matches_search",
     "_column_index", "_checklist_progress", "_unchecked_count", "_parse_stamp",
     "_time_log_summary", "_has_logged_work", "_has_sprint_details"],
    COLUMN_ORDER=COLUMN_ORDER, escape=html.escape, datetime=datetime, timezone=timezone,
    task_tags=task_tags, task_matches_tag_query=task_matches_tag_query,
)


@pytest.mark.unit
def test_as_id_accepts_digits_only():
    assert ns["_as_id"]("12") == 12
    assert ns["_as_id"](7) == 7
    for bad in (None, "", "abc", "1.5", "-3"):
        assert ns["_as_id"](bad) is None


@pytest.mark.unit
def test_normalized_task_id_strips_dom_prefix():
    assert ns["_normalized_task_id"]("task-42") == "42"
    assert ns["_normalized_task_id"]("42") == "42"
    assert ns["_normalized_task_id"](None) == ""
    assert ns["_normalized_task_id"](42) == "42"


@pytest.mark.unit
def test_column_index_follows_board_order():
    assert [ns["_column_index"](c) for c in COLUMN_ORDER] == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        ns["_column_index"]("nowhere")


@pytest.mark.unit
def test_tag_chips_html_escapes_and_handles_untagged():
    assert ns["_tag_chips_html"]({}) == ""
    out = ns["_tag_chips_html"]({"tags": ["ui", "api"]})
    assert out.count("task-tag-chip") == 2
    assert out.startswith('<div class="task-card-tags">')


@pytest.mark.unit
def test_task_matches_search():
    task = {"tags": ["frontend"]}
    assert ns["_task_matches_search"](task, "")
    assert ns["_task_matches_search"](task, "front")
    assert not ns["_task_matches_search"](task, "back")


@pytest.mark.unit
def test_checklist_progress_and_unchecked_count():
    task = {"checklist": [{"done": True}, {"done": False}, {"done": True}, {}]}
    assert ns["_checklist_progress"](task) == (2, 4, 50)
    assert ns["_unchecked_count"](task) == 2
    assert ns["_checklist_progress"]({}) == (0, 0, 0)
    assert ns["_unchecked_count"]({}) == 0


@pytest.mark.unit
def test_parse_stamp():
    assert ns["_parse_stamp"](None) is None
    assert ns["_parse_stamp"]("") is None
    assert ns["_parse_stamp"]("garbage") is None
    aware = ns["_parse_stamp"]("2026-10-01T10:00:00+00:00")
    naive = ns["_parse_stamp"]("2026-10-01T10:00:00")   # naive is read as UTC
    assert aware == naive
    assert aware.tzinfo is not None


@pytest.mark.unit
def test_time_log_summary_no_log():
    assert ns["_time_log_summary"]({}) == ("", "", "", "")
    assert ns["_time_log_summary"]({"time_log": {}}) == ("", "", "", "")


@pytest.mark.unit
def test_time_log_summary_sums_finished_sessions():
    task = {"time_log": {"entries": [
        {"started_at": "2026-10-01T09:00:00+00:00", "ended_at": "2026-10-01T10:30:00+00:00"},
        {"started_at": "2026-10-02T09:00:00+00:00", "ended_at": "2026-10-02T09:45:00+00:00"},
    ]}}
    started, ended, duration, status = ns["_time_log_summary"](task)
    assert duration == "2h 15m"
    assert status == "2h 15m"
    assert started and ended


@pytest.mark.unit
def test_time_log_summary_reports_running_session():
    task = {"time_log": {"entries": [
        {"started_at": "2026-10-01T09:00:00+00:00", "ended_at": None}]}}
    _, _, duration, status = ns["_time_log_summary"](task)
    assert status == "In progress"
    assert duration == "0m"


@pytest.mark.unit
def test_time_log_summary_reads_legacy_flat_log_and_minutes_only():
    task = {"time_log": {"started_at": "2026-10-01T09:00:00+00:00",
                         "ended_at": "2026-10-01T09:20:00+00:00"}}
    assert ns["_time_log_summary"](task)[2] == "20m"


@pytest.mark.unit
def test_time_log_summary_skips_unreadable_entries():
    task = {"time_log": {"entries": [{"started_at": "bad", "ended_at": "bad"}, "junk"]}}
    assert ns["_time_log_summary"](task) == ("", "", "", "")


@pytest.mark.unit
def test_has_logged_work_and_sprint_details():
    assert not ns["_has_logged_work"]({})
    assert ns["_has_logged_work"]({"time_log": {"started_at": "x"}})
    assert ns["_has_logged_work"]({"time_log": {"entries": [{}]}})
    assert not ns["_has_sprint_details"]({})
    for field in ({"checklist": [1]}, {"assignee": "a"}, {"assignee_id": 0},
                  {"start_date": "d"}, {"end_date": "d"}, {"feedback": [1]}):
        assert ns["_has_sprint_details"](field)