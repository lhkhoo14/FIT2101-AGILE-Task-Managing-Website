"""Pure logic modules: sprint_logic, contribution_logic, membership_logic."""
from datetime import date, datetime, timedelta, timezone

import pytest

import logic.contribution_logic as cl
import logic.membership_logic as ml
import logic.sprint_logic as sl

TODAY = date(2026, 10, 20)


def t(task_id, title="T", **extra):
    return {"id": task_id, "title": title, **extra}


def board(**cols):
    return {"backlog": [], "active": [], "review": [], "completed": [], **cols}


# ======================== sprint_logic ======================================
@pytest.mark.unit
def test_dates_parse_and_validate():
    assert sl.parse_date("2026-10-20") == TODAY
    with pytest.raises(ValueError, match="Start"):
        sl.parse_date("nope", "Start")
    assert sl.validate_sprint_dates("2026-10-20", "2026-10-30", TODAY) == (TODAY, date(2026, 10, 30))
    with pytest.raises(ValueError, match="before the start"):
        sl.validate_sprint_dates("2026-10-30", "2026-10-20", TODAY)
    with pytest.raises(ValueError, match="past"):
        sl.validate_sprint_dates("2026-10-01", "2026-10-10", TODAY)
    assert sl.today() == date.today()


@pytest.mark.unit
def test_sprint_bounds_and_auto_complete():
    assert sl.sprint_bounds({}) == (None, None)
    assert sl.sprint_bounds({"start_date": "x", "end_date": "y"}) == (None, None)
    project = {"sprints": [
        {"start_date": "2026-10-01", "end_date": "2026-10-10", "status": "active"},
        {"start_date": "2026-10-01", "end_date": "2026-10-25", "status": "active"},
        {"status": "active"},
        {"start_date": "2026-10-01", "end_date": "2026-10-10", "status": "ended"},
    ]}
    assert sl.auto_complete_sprints(project, TODAY) is True
    assert [s["status"] for s in project["sprints"]] == ["ended", "active", "active", "ended"]
    assert project["sprints"][0]["ended_at"] == "2026-10-10" and project["sprints"][0]["auto_completed"]
    assert sl.auto_complete_sprints(project, TODAY) is False
    assert sl.auto_complete_sprints({}, TODAY) is False


@pytest.mark.unit
def test_task_dates_validation():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-10"}
    sl.validate_task_dates(board(active=[t(1, start_date="2026-10-02", end_date="2026-10-09"), t(2)]), sprint)
    with pytest.raises(ValueError, match="before its start"):
        sl.validate_task_dates(board(active=[t(1, start_date="2026-10-05", end_date="2026-10-04")]), sprint)
    with pytest.raises(ValueError, match="within the sprint"):
        sl.validate_task_dates(board(active=[t(1, end_date="2026-11-01")]), sprint)
    with pytest.raises(ValueError, match="valid date"):
        sl.validate_task_dates(board(active=[t(1, start_date="junk")]), sprint)
    sl.validate_task_dates(board(active=[t(1, start_date="2099-01-01")]), {})    # undated sprint: no bounds


@pytest.mark.unit
def test_checklists_gate_completion():
    open_task = t(1, checklist=[{"done": True}, {"done": False}, {"done": False}])
    assert len(sl.unchecked_checklist_items(open_task)) == 2
    assert sl.unchecked_checklist_items({}) == []
    with pytest.raises(ValueError, match="2 unchecked checklist items"):
        sl.validate_completion_checklists({}, board(completed=[open_task]))
    with pytest.raises(ValueError, match="1 unchecked checklist item\\."):
        sl.validate_completion_checklists({}, board(completed=[t(1, checklist=[{"done": False}])]))
    # Already completed before this save: left alone.
    sl.validate_completion_checklists(board(completed=[open_task]), board(completed=[open_task]))
    sl.validate_completion_checklists(None, board(completed=[t(2, checklist=[{"done": True}])]))


@pytest.mark.unit
def test_stamp_completions():
    sprint = {"start_date": "2026-10-01", "end_date": "2026-10-30"}
    old = board(completed=[t(1, completed_at="2026-10-05"), t(2, completed_at=None)])
    new = board(completed=[t(1), t(2), t(3)], active=[t(4, completed_at="old")])
    sl.stamp_completions(old, new, sprint, TODAY)
    done = {task["id"]: task["completed_at"] for task in new["completed"]}
    assert done == {1: "2026-10-05", 2: "2026-10-01", 3: "2026-10-20"}
    assert "completed_at" not in new["active"][0]
    undated = board(completed=[t(1)])
    sl.stamp_completions(board(completed=[t(1, completed_at=None)]), undated, {}, TODAY)
    assert undated["completed"][0]["completed_at"] == "2026-10-20"


@pytest.mark.unit
def test_sprint_member_validation():
    project = {"members": [1, "2", "x", 3]}
    assert sl.validate_sprint_members(None, project) == []
    assert sl.validate_sprint_members([1, "2", 2, 1], project) == [1, 2]
    with pytest.raises(ValueError, match="9, abc"):
        sl.validate_sprint_members([9, "abc"], project)


@pytest.mark.unit
def test_assignee_validation_only_checks_changes():
    project = {"members": [1, 2]}
    sl.validate_assignees(None, board(active=[t(1, assignee_id=2), t(2)]), project)
    old = board(active=[t(1, assignee_id=99)])
    sl.validate_assignees(old, board(active=[t(1, assignee_id=99)]), project)       # unchanged legacy assignee
    with pytest.raises(ValueError, match="not a member"):
        sl.validate_assignees(old, board(active=[t(1, assignee_id=98)]), project)
    with pytest.raises(ValueError, match="invalid assignee"):
        sl.validate_assignees(None, board(active=[t(1, assignee_id="x")]), project)


@pytest.mark.unit
def test_tags_and_descriptions():
    assert sl.normalize_tags("Front, #API ,, api") == ["front", "api"]
    assert sl.normalize_tags(None) == [] and sl.normalize_tags(["A" * 40]) == ["a" * 20]
    assert len(sl.normalize_tags([f"t{i}" for i in range(30)])) == sl.MAX_TAGS
    assert sl.task_tags({"tags": ["X"]}) == ["x"] and sl.task_tags({"tag": "Old"}) == ["old"] and sl.task_tags({}) == []
    assert sl.clean_description("  hi ") == "hi" and sl.clean_description(None) == ""
    sl.validate_descriptions(board(active=[t(1), t(2, description=None), t(3, description="ok")]))
    with pytest.raises(ValueError, match="must be text"):
        sl.validate_descriptions(board(active=[t(1, description=3)]))
    with pytest.raises(ValueError, match="too long"):
        sl.validate_descriptions(board(active=[t(1, description="x" * 1001)]))
    old = board(active=[t(1, description="a")])
    assert sl.descriptions_changed(old, board(active=[t(1, description="b")]))
    assert sl.descriptions_changed(old, board(active=[t(1, description="a"), t(2, description="new")]))
    assert not sl.descriptions_changed(old, board(active=[t(1, description=" a ")]))
    assert not sl.descriptions_changed(None, board(active=[t(1)]))


@pytest.mark.unit
def test_sprint_membership_and_leadership():
    assert sl.is_sprint_member({}, 5) and sl.is_sprint_member({"members": [1, "2"]}, "2")
    assert not sl.is_sprint_member({"members": [1]}, 2) and not sl.is_sprint_member({"members": [1]}, "x")
    assert not sl.is_sprint_member({"members": [None]}, 1)
    project = {"roles": {"Project Creator": [1], "Scrum Master": ["2", "bad"], "Product Owner": [1], "Manager": [9]},
               "sprints": [{"members": [3, "3", "junk"]}, {"members": None}, {"members": [1, 2]}]}
    assert sl.leadership_member_ids(project) == [1, 2]
    assert sl.leadership_member_ids({}) == []
    assert sl.ensure_leadership_membership(project) is True
    assert project["sprints"][0]["members"] == [3, 1, 2] and project["sprints"][1]["members"] is None
    assert sl.ensure_leadership_membership(project) is False
    assert sl.ensure_leadership_membership({"sprints": [{"members": []}]}) is False


@pytest.mark.unit
def test_task_id_helpers():
    assert sl.normalized_task_id("task-7") == "7" and sl.normalized_task_id(None) == "" and sl.normalized_task_id(7) == "7"
    assert sl.has_logged_work({"time_log": {"started_at": "x"}}) and sl.has_logged_work({"time_log": {"entries": [1]}})
    assert not sl.has_logged_work({}) and not sl.has_logged_work({"time_log": {}})
    assert sl.backlog_id_for_task({"id": "task-5"}, set(), 50) == (5, False)
    assert sl.backlog_id_for_task({"id": "task-5"}, {5}, 50) == (50, True)
    assert sl.backlog_id_for_task({"id": "abc"}, set(), 50) == (50, True)


@pytest.mark.unit
def test_finding_and_removing_tasks():
    state = board(active=[t("task-1", "One")], completed=[t("2", "Two")])
    assert sl.find_board_task(state, "1")[0] == "active" and sl.find_board_task(state, "task-2")[0] == "completed"
    assert sl.find_board_task(state, "9") == (None, None) and sl.find_board_task(None, "1") == (None, None)
    assert sl.task_delete_blocker(state, "1") is None
    assert "completed" in sl.task_delete_blocker(state, "2")
    assert "not found" in sl.task_delete_blocker(state, "9")
    assert sl.removed_tasks(state, board(completed=[t("2")])) == [("1", "One", "active")]
    assert sl.removed_tasks(None, state) == []


# ======================== contribution_logic ================================
@pytest.mark.unit
def test_stamps_and_ids():
    moment = datetime(2026, 10, 20, 8, 30, tzinfo=timezone.utc)
    assert cl.utc_stamp(moment) == "2026-10-20 08:30 UTC" and cl.utc_iso(moment).startswith("2026-10-20T08:30")
    assert cl.utc_now().tzinfo is not None and cl.utc_stamp() and cl.utc_iso()
    assert cl.as_id(True) is None and cl.as_id(5) == 5 and cl.as_id(" 7 ") == 7 and cl.as_id("-3") == -3 and cl.as_id("x") is None
    assert cl.member_ids({"members": [1, "1", "x", 2, None]}) == [1, 2]
    assert cl.member_ids({}) == []


@pytest.mark.unit
def test_owner_matching():
    users = [{"user_id": 1, "username": "John Smith", "email": "j@x.com"},
             {"user_id": 2, "username": "", "email": "k@x.com"}, {"user_id": 9, "username": "Out"}, {"user_id": "x"}]
    mapping = cl.name_to_id_map(users, [1, 2])
    assert mapping == {"john smith": 1, "j@x.com": 1, "k@x.com": 2}
    assert cl.resolve_owner({"assignee_id": 1}, [1, 2], mapping) == 1
    assert cl.resolve_owner({"assignee_id": 7}, [1, 2], mapping) is None
    assert cl.resolve_owner({"assignee": "John Smith"}, [1], mapping) == 1
    assert cl.resolve_owner({"assignee": "Smith"}, [1], mapping) == 1          # suffix match
    assert cl.resolve_owner({"assignee": "  "}, [1], mapping) is None and cl.resolve_owner({}, [1], mapping) is None
    assert cl.resolve_owner({"assignee": "Nobody"}, [1], mapping) is None
    assert cl.display_name({1: {"username": "a"}}, 1) == "a" and cl.display_name({1: {"email": "e"}}, 1) == "e"
    assert cl.display_name({}, 4) == "User 4"


@pytest.mark.unit
def test_work_log_lifecycle_and_seconds():
    start = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    task = {}
    entry = cl.start_work_log(task, 1, start)
    assert entry["ended_at"] is None and cl.start_work_log(task, 2, start) is entry
    assert cl.open_entry(task) is entry and cl.open_entry(task, 1) is entry
    assert cl.task_seconds(task) == 0
    cl.stop_work_log(task, 1, start + timedelta(minutes=90))
    assert cl.task_seconds(task) == 5400 and cl.open_entry(task) is None
    with pytest.raises(ValueError):
        cl.stop_work_log(task, 1)
    # Legacy flat log, and sessions with no recorded user.
    legacy = {"time_log": {"started_at": start.isoformat(), "ended_at": (start + timedelta(seconds=30)).isoformat()}}
    assert cl.log_entries(legacy)[0]["user_id"] is None and cl.task_seconds(legacy) == 30
    assert cl.log_entries({}) == [] and cl.log_entries({"time_log": {"entries": []}}) == []
    orphan = {"time_log": {"entries": [{"started_at": start.isoformat(), "ended_at": None}]}}
    cl.stop_work_log(orphan, 7, start + timedelta(seconds=5))
    assert orphan["time_log"]["entries"][0]["user_id"] == 7
    assert cl.entry_seconds({}) == 0 and cl.entry_seconds({"started_at": "bad", "ended_at": "bad"}) == 0
    assert cl.entry_seconds({"started_at": "2026-10-20T10:00:00+00:00", "ended_at": "2026-10-20T09:00:00+00:00"}) == 0
    other = {"time_log": {"entries": [{"user_id": 4, "started_at": "x", "ended_at": None}]}}
    assert cl.open_entry(other, 5) is None and cl.open_entry(other, 4) is not None


@pytest.mark.unit
def test_compute_contributions():
    users = [{"user_id": 1, "username": "alice"}, {"user_id": 2, "username": "bob"}]
    session = {"user_id": 2, "started_at": "2026-10-20T08:00:00+00:00", "ended_at": "2026-10-20T09:30:00+00:00"}
    project = {"members": [1, 2], "sprints": [{
        "id": "s1", "name": "Sprint", "kanban_state": board(
            active=[t(1, "B task", assignee_id=1, time_log={"entries": [session]}), t(2, "Unassigned",
                    time_log={"entries": [{"user_id": 2, "started_at": "a", "ended_at": None}]})],
            completed=[t(3, "A task", assignee="alice"), t(4, "Outsider", assignee_id=77)])}]}
    stats = cl.compute_contributions(project, users)
    alice, bob = stats["members"]
    assert (alice["name"], alice["assigned"], alice["completed"]) == ("alice", 2, 1)
    assert [x["title"] for x in alice["tasks"]] == ["A task", "B task"]          # completed first
    assert bob["logged_seconds"] == 5400 and bob["logged_hours"] == 1.5 and len(bob["work_logs"]) == 2
    assert stats["total_logged_seconds"] == 5400
    assert [m["user_id"] for m in cl.compute_contributions(project, users, allowed_ids=[2])["members"]] == [2]
    assert cl.compute_contributions({}, None) == {"members": [], "total_logged_seconds": 0}
    # A session with no logger is credited to the task's owner.
    anon = {"members": [1], "sprints": [{"id": "s", "kanban_state": board(
        active=[t(1, assignee_id=1, time_log={"entries": [{"started_at": "2026-10-20T08:00:00+00:00", "ended_at": "2026-10-20T08:01:00+00:00"}]})])}]}
    assert cl.compute_contributions(anon, users)["members"][0]["logged_seconds"] == 60


@pytest.mark.unit
def test_find_task():
    project = {"sprints": [{"id": 3, "kanban_state": board(active=[t("task-5", "A"), t("6", "B")])}]}
    assert cl.find_task(project, "3", "5")["title"] == "A"
    assert cl.find_task(project, 3, "task-6")["title"] == "B"
    with pytest.raises(ValueError, match="Sprint"):
        cl.find_task(project, "9", "5")
    with pytest.raises(ValueError, match="Task"):
        cl.find_task(project, "3", "99")


# ======================== membership_logic ==================================
def project_with_roles():
    return {
        "members": [1, 2, 3, 4, 5],
        "roles": {"Project Creator": [1], "Scrum Master": [2], "Employee": [3, "4"], "Custom": [5], "Bad": "oops"},
        "role_definitions": {
            "Project Creator": {"permissions": ["a", "b", "c"]}, "Scrum Master": {"permissions": ["a", "b"]},
            "Employee": {"permissions": ["a"]}, "Custom": {"permissions": ["a", "z"]}, "Bad": "x"},
    }


@pytest.mark.unit
def test_permissions_and_rank():
    p = project_with_roles()
    assert ml.permissions_for(p, 2) == {"a", "b"} and ml.permissions_for(p, "x") == set() and ml.permissions_for(p, 99) == set()
    assert ml.highest_preset_rank(p, 1) == 5 and ml.highest_preset_rank(p, 5) == ml.UNRANKED
    assert ml.highest_preset_rank(p, "x") == ml.UNRANKED and ml.highest_preset_rank({}, 1) == ml.UNRANKED


@pytest.mark.unit
def test_can_remove_member():
    p = project_with_roles()
    assert ml.can_remove_member(p, 1, 2) and ml.can_remove_member(p, 2, 3)
    assert not ml.can_remove_member(p, 3, 2) and not ml.can_remove_member(p, 1, 1)
    assert not ml.can_remove_member(p, None, 1) and not ml.can_remove_member(p, 1, "x")
    assert ml.can_remove_member(p, 3, 5) is False               # custom role holds more than Employee: veto
    p["roles"]["Employee"].append(5)
    assert not ml.can_remove_member(p, 4, 3)                    # equal rank, equal permissions
    p["role_definitions"]["Employee"]["permissions"] = ["a", "b", "c", "d"]
    assert ml.can_remove_member(p, 3, 4) is False
    assert ml.can_remove_member({"roles": {"Employee": [1], "Custom": [2]}, "role_definitions": {"Custom": {"permissions": ["big", "bigger"]}}}, 1, 2) is False


@pytest.mark.unit
def test_creators():
    assert ml.creator_ids({"roles": {"Project Creator": [1, "1", "x", 2]}}) == [1, 2]
    assert ml.creator_ids({"creator": [5]}) == [5] and ml.creator_ids({}) == []
    assert ml.is_sole_creator({"roles": {"Project Creator": [1]}}, 1)
    assert not ml.is_sole_creator({"roles": {"Project Creator": [1, 2]}}, 1) and not ml.is_sole_creator({}, "x")
    projects = [{"roles": {"Project Creator": [1]}, "members": [1]}, {"roles": {"Project Creator": [1]}, "members": [2]},
                {"roles": {"Project Creator": [2]}, "members": [1, 2]}]
    assert ml.sole_creator_projects(projects, 1) == [projects[0]] and ml.sole_creator_projects(None, 1) == []


@pytest.mark.unit
def test_detach_member_clears_every_trace():
    p = {"members": [1, 2], "contribute": [1, 2], "roles": {"Employee": [2, "2"], "Odd": "x"},
         "sprints": [{"members": [1, 2], "kanban_state": board(active=[t(1, assignee_id=2, assignee="bob"), t(2, assignee_id=1)])},
                     {"members": None}]}
    assert ml.detach_member(p, 2) is True
    assert p["members"] == [1] and p["contribute"] == [1] and p["roles"]["Employee"] == []
    assert p["sprints"][0]["members"] == [1]
    tasks = p["sprints"][0]["kanban_state"]["active"]
    assert tasks[0]["assignee_id"] is None and tasks[0]["assignee"] is None and tasks[1]["assignee_id"] == 1
    assert ml.detach_member(p, 2) is False and ml.detach_member(p, "x") is False
    assert ml.unassign_tasks(None, 1) is False