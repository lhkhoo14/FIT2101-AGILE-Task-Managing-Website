from datetime import date

import pytest

import frontend_paths  # noqa: F401
import charts


def _task(**extra):
    return {"id": "t", "title": "T", **extra}


@pytest.mark.unit
def test_parse_iso_and_format_day():
    assert charts.parse_iso("2026-10-05") == date(2026, 10, 5)
    assert charts.parse_iso(None) is None
    assert charts.parse_iso("not a date") is None
    assert charts.format_day(date(2026, 10, 5)) == "Oct 5"
    assert charts.format_day(date(2026, 10, 5), with_year=True) == "Oct 5, 2026"


@pytest.mark.unit
def test_burndown_series_none_for_legacy_or_invalid_dates():
    assert charts.burndown_series({}, {}, date(2026, 10, 5)) is None
    backwards = {"start_date": "2026-10-10", "end_date": "2026-10-01"}
    assert charts.burndown_series(backwards, {}, date(2026, 10, 5)) is None


@pytest.mark.unit
def test_burndown_series_running_sprint_stops_at_today():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-05", "status": "active"}
    state = {
        "backlog": [_task()],
        "active": [_task()],
        "completed": [_task(completed_at="2026-10-02"), _task(completed_at="2026-10-03")],
    }
    series = charts.burndown_series(sprint, state, date(2026, 10, 3))
    assert series["total"] == 4
    assert series["completed"] == 2
    assert len(series["days"]) == 5
    remaining = [d["remaining"] for d in series["days"]]
    assert remaining == [4, 3, 2, None, None]   # nothing after "today"
    assert series["days"][0]["ideal"] == 4
    assert series["days"][-1]["ideal"] == 0


@pytest.mark.unit
def test_burndown_series_completed_without_date_counts_from_start():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-03", "status": "active"}
    state = {"completed": [_task()]}
    series = charts.burndown_series(sprint, state, date(2026, 10, 3))
    assert series["days"][0]["completed"] == 1


@pytest.mark.unit
def test_burndown_series_ended_sprint_uses_ended_at():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-10",
              "status": "ended", "ended_at": "2026-10-04"}
    series = charts.burndown_series(sprint, {"backlog": [_task()]}, date(2026, 10, 9))
    known = [d for d in series["days"] if d["remaining"] is not None]
    assert len(known) == 4


@pytest.mark.unit
def test_burndown_series_single_day_sprint_and_missing_state():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-01"}
    series = charts.burndown_series(sprint, None, date(2026, 10, 1))
    assert series["total"] == 0
    assert len(series["days"]) == 1
    assert series["days"][0]["ideal"] == 0


@pytest.mark.unit
def test_burndown_svg_renders_chart_and_escapes():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-12", "status": "active"}
    state = {"backlog": [_task(), _task()], "completed": [_task(completed_at="2026-10-02")]}
    svg = charts.burndown_svg(charts.burndown_series(sprint, state, date(2026, 10, 6)))
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "Burndown chart" in svg
    assert "polyline" in svg and "circle" in svg
    assert "Tasks remaining" in svg


@pytest.mark.unit
def test_burndown_svg_handles_one_day_and_empty_sprint():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-01"}
    svg = charts.burndown_svg(charts.burndown_series(sprint, {}, date(2026, 10, 1)))
    assert "<svg" in svg


@pytest.mark.unit
def test_effort_counts_groups_and_sorts():
    states = [
        {"completed": [{"assignee": "Bob"}, {"assignee": "alice"}, {"assignee": ""}]},
        {"completed": [{"assignee": "Bob"}, {}]},
        None,
    ]
    counts = charts.effort_counts(states)
    # Bob and Unassigned both have 2; ties are ordered by name.
    assert [name for name, _ in counts] == ["Bob", charts.UNASSIGNED, "alice"]
    assert dict(counts)["alice"] == 1
    assert dict(counts)[charts.UNASSIGNED] == 2


@pytest.mark.unit
def test_pie_svg_empty_single_and_multiple():
    assert charts.pie_svg([]) == ""
    assert charts.pie_svg([("A", 0)]) == ""
    single = charts.pie_svg([("A", 3)])
    assert "<circle" in single and "100%" in single
    multi = charts.pie_svg([("A", 3), ("B", 1)])
    assert multi.count("<path") == 2
    assert "75%" in multi
    assert "B: 1 task (25%)" in multi


@pytest.mark.unit
def test_pie_svg_hides_label_for_tiny_slices_and_escapes_names():
    svg = charts.pie_svg([("<b>big</b>", 99), ("tiny", 1)])
    assert "&lt;b&gt;big&lt;/b&gt;" in svg
    assert "<b>big</b>" not in svg
    assert svg.count("font-weight=\"700\"") == 1   # only the large slice is labelled


@pytest.mark.unit
def test_pie_legend_html():
    html_out = charts.pie_legend_html([("Ann", 2), ("<x>", 1)])
    assert "2 tasks" in html_out and "1 task " in html_out
    assert "&lt;x&gt;" in html_out
    assert "67%" in html_out