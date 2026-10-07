from datetime import date, timedelta
from itertools import permutations, product

import pytest

from cleaning_app.scheduler import (
    ROOMS, TASKS, due_bundles, initial_phases, make_plan, month_number,
    job_units, room_tasks, task_interval,
)


def plan_for(kind="other", today=date(2026, 10, 5), latest=None, completed=(), tasks=None, rooms=None):
    return make_plan(today, date(2026, 10, 1), initial_phases(ROOMS), latest or {}, completed,
                     tasks or TASKS, rooms or ROOMS, kind)


def test_initial_cohorts_balance_room_sizes():
    phases = initial_phases(ROOMS)
    assert sorted(sum(ROOMS[r] for r, phase in phases.items() if phase == i) for i in range(3)) == [9, 10, 11]


def test_sunday_only_dust_or_shower_and_mops_have_vacuum_partners():
    sunday = plan_for("sunday")
    assert sunday["jobs"]
    assert all(j["task"] in {"dust", "shower"} for j in sunday["jobs"])
    for day in sunday["days"]:
        jobs = {(j["room"], j["task"]) for j in day["jobs"]}
        assert all((room, "vacuum") in jobs for room, task in jobs if task == "mop")


def test_all_due_jobs_are_allocated_exactly_once():
    plan = plan_for()
    jobs = [(j["room"], j["task"]) for day in plan["days"] for j in day["jobs"]]
    bundles = due_bundles(date(2026, 10, 5), date(2026, 10, 1), initial_phases(ROOMS), {}, TASKS, ROOMS)
    expected = {(b.room, t) for b in bundles for t in b.tasks}
    assert len(jobs) == len(set(jobs))
    assert set(jobs) == expected
    assert sum(d["units"] for d in plan["days"]) == sum(b.units for b in bundles)


def test_partition_is_globally_optimal_for_initial_month():
    bundles = due_bundles(date(2026, 10, 5), date(2026, 10, 1), initial_phases(ROOMS), {}, TASKS, ROOMS)
    possible = [(0, 2) if b.floor else (0, 1, 2) for b in bundles]
    optimum = min(sum(sum(b.units for b, target in zip(bundles, assignment) if target == slot) ** 2
                      for slot in range(3)) for assignment in product(*possible))
    plan = plan_for()
    assert sum(d["units"] ** 2 for d in plan["days"]) == optimum


@pytest.mark.parametrize("kinds", sorted(set(permutations(["sunday", "other", "other"]))))
def test_two_years_meet_cadence_in_three_days_per_month(kinds):
    phases = initial_phases(ROOMS)
    latest = {}
    started = date(2026, 10, 1)
    all_loads = []
    for month in range(24):
        number = month_number(started) + month
        first = date(number // 12, number % 12 + 1, 1)
        done_days = []
        cursor = first
        month_loads = []
        for kind in kinds:
            while (cursor.weekday() == 6) != (kind == "sunday"):
                cursor += timedelta(days=1)
            plan = make_plan(cursor, started, phases, latest, done_days, TASKS, ROOMS, kind)
            for job in plan["jobs"]:
                assert job["task"] in {"dust", "shower"} or cursor.weekday() != 6
                key = (job["room"], job["task"])
                if key in latest:
                    assert number - month_number(latest[key]) <= task_interval(*key)
                latest[key] = cursor
            if plan["jobs"]:
                done_days.append(cursor)
            month_loads.append(plan["units"])
            cursor += timedelta(days=7)
        remaining = due_bundles(first.replace(day=28), started, phases, latest, TASKS, ROOMS)
        assert remaining == []
        assert all(month_number(latest[(room, "dust")]) == number for room in ROOMS)
        assert month_number(latest[("bath", "shower")]) == number
        for room in ROOMS:
            for task in room_tasks(room):
                interval = task_interval(room, task)
                if month >= interval - 1:
                    assert (room, task) in latest
                    assert number - month_number(latest[(room, task)]) < interval
        all_loads.extend(month_loads)
    # The shower alone weighs 60; all regular sessions stay within the limit.
    assert max(all_loads) <= plan["workload_limit"]


def test_overdue_work_is_carried_forward_and_empty_sunday_defers_floor_work():
    today = date(2027, 4, 25)  # Sunday, with both weekday sessions used.
    latest = {(room, "dust"): date(2027, 4, 3) for room in ROOMS}
    latest["bath", "shower"] = date(2027, 4, 3)
    plan = plan_for("sunday", today, latest, [date(2027, 4, 3), date(2027, 4, 10)])
    assert plan["jobs"] == []
    assert len(plan["deferred"]) == 12
    assert all(j["overdue"] for j in plan["deferred"])
    later = plan_for("other", date(2027, 4, 26), latest, [date(2027, 4, 3), date(2027, 4, 10)])
    assert 0 < len(later["jobs"]) < 12
    assert later["units"] <= later["workload_limit"]
    assert len(later["jobs"]) + len(later["deferred"]) == 12


def test_kitchen_mopping_starts_immediately_and_repeats_monthly():
    phases = initial_phases(ROOMS)
    assert phases["kitchen"] == 2
    started = date(2026, 10, 1)
    bundles = due_bundles(started, started, phases, {}, TASKS, ROOMS)
    assert any(b.room == "kitchen" and b.tasks == ("vacuum", "mop") for b in bundles)
    latest = {(room, task): date(2026, 10, 26) for room in ROOMS for task in room_tasks(room)}
    for month in (11, 12, 1):
        today = date(2027 if month == 1 else 2026, month, 1)
        bundles = due_bundles(today, started, phases, latest, TASKS, ROOMS)
        mopped = {b.room for b in bundles if "mop" in b.tasks}
        assert mopped == (set(ROOMS) if month == 1 else {"kitchen"})


@pytest.mark.parametrize("delay", [7, 28, 180])
def test_missed_sessions_do_not_increase_the_usual_workload(delay):
    started = date(2026, 10, 1)
    phases = initial_phases(ROOMS)
    latest = {}
    completed = []
    for kind, day in [("other", date(2026, 10, 5)), ("sunday", date(2026, 10, 11))]:
        plan = make_plan(day, started, phases, latest, completed, TASKS, ROOMS, kind)
        for job in plan["jobs"]:
            latest[job["room"], job["task"]] = day
        completed.append(day)
    scheduled_day = date(2026, 10, 26)
    on_time = make_plan(scheduled_day, started, phases, latest, completed, TASKS, ROOMS, "other")
    delayed_day = scheduled_day + timedelta(days=delay)
    delayed = make_plan(delayed_day, started, phases, latest, completed, TASKS, ROOMS, "other")
    assert delayed["workload_limit"] == on_time["workload_limit"]
    assert all(day["units"] <= on_time["workload_limit"] for day in delayed["days"])
    due = {(b.room, task) for b in due_bundles(delayed_day, started, phases, latest, TASKS, ROOMS)
           for task in b.tasks}
    assigned = [(j["room"], j["task"]) for day in delayed["days"] for j in day["jobs"]]
    carried = [(j["room"], j["task"]) for j in delayed["deferred"]]
    assert set(assigned + carried) == due
    assert len(assigned + carried) == len(due)
    assert delayed["jobs"]


def test_overdue_work_progresses_without_a_catch_up_session():
    today = date(2027, 4, 5)
    latest = {(room, "dust"): today for room in ROOMS}
    completed = [date(2027, 4, 1), date(2027, 4, 3)]
    remaining = {(room, task) for room in ROOMS for task in ("vacuum", "mop")}
    for _ in range(6):
        plan = plan_for("other", today, latest, completed)
        assert plan["units"] <= plan["workload_limit"]
        for job in plan["jobs"]:
            key = job["room"], job["task"]
            latest[key] = today
            remaining.discard(key)
        if plan["jobs"]:
            completed.append(today)
        today += timedelta(days=7)
    assert not remaining


def test_configuration_changes_job_costs():
    tasks = {"vacuum": 3, "dust": 4, "mop": 8, "shower": 60}
    rooms = {**ROOMS, "living": 20}
    plan = plan_for(tasks=tasks, rooms=rooms)
    for day in plan["days"]:
        assert day["units"] == sum(j["units"] for j in day["jobs"])
        assert all(j["units"] == job_units(j["room"], j["task"], tasks, rooms) for j in day["jobs"])


def test_calendar_months_handle_year_and_leap_boundaries():
    latest = {(room, "dust"): date(2027, 12, 31) for room in ROOMS}
    bundles = due_bundles(date(2028, 1, 1), date(2027, 12, 1), initial_phases(ROOMS), latest, TASKS, ROOMS)
    assert sum(b.tasks == ("dust",) for b in bundles) == 6
    latest = {(room, "vacuum"): date(2028, 2, 29) for room in ROOMS}
    bundles = due_bundles(date(2028, 4, 1), date(2028, 2, 1), initial_phases(ROOMS), latest, TASKS, ROOMS)
    assert all(any(b.room == room and "vacuum" in b.tasks for b in bundles) for room in ROOMS)


@pytest.mark.parametrize("kind", ["sunday", "other"])
def test_shower_can_be_scheduled_on_either_day_with_60_total_units(kind):
    today = date(2026, 10, 25)
    latest = {(room, task): today for room in ROOMS for task in room_tasks(room) if task != "shower"}
    rooms = {**ROOMS, "bath": 10}
    plan = plan_for(kind, today, latest, tasks=TASKS, rooms=rooms)
    assert plan["jobs"] == [{"room": "bath", "task": "shower", "units": 60, "overdue": False}]
    assert plan["units"] == 60
    assert plan["workload_limit"] >= 60


def test_shower_is_one_job_due_initially_and_every_calendar_month():
    started = date(2026, 12, 1)
    phases = initial_phases(ROOMS)

    def showers(today, latest):
        return [b for b in due_bundles(today, started, phases, latest, TASKS, ROOMS) if "shower" in b.tasks]

    initial = showers(started, {})
    assert len(initial) == 1
    assert (initial[0].room, initial[0].units, initial[0].due) == ("bath", 60, month_number(started))
    latest = {("bath", "shower"): date(2026, 12, 31)}
    assert showers(date(2026, 12, 31), latest) == []
    assert len(showers(date(2027, 1, 1), latest)) == 1
    assert showers(date(2027, 2, 1), latest)[0].due == month_number(date(2027, 1, 1))
    latest["bath", "shower"] = date(2027, 2, 28)
    assert showers(date(2027, 2, 28), latest) == []
    assert len(showers(date(2027, 3, 1), latest)) == 1
