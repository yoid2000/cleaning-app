from datetime import date, timedelta
from itertools import permutations, product

import pytest

from cleaning_app.scheduler import (
    INTERVALS, ROOMS, TASKS, due_bundles, initial_phases, make_plan, month_number,
)


def plan_for(kind="other", today=date(2026, 10, 5), latest=None, completed=(), tasks=None, rooms=None):
    return make_plan(today, date(2026, 10, 1), initial_phases(ROOMS), latest or {}, completed,
                     tasks or TASKS, rooms or ROOMS, kind)


def test_initial_cohorts_balance_room_sizes():
    phases = initial_phases(ROOMS)
    assert sorted(sum(ROOMS[r] for r, phase in phases.items() if phase == i) for i in range(3)) == [9, 10, 11]


def test_sunday_only_dust_and_mops_have_vacuum_partners():
    sunday = plan_for("sunday")
    assert sunday["jobs"]
    assert all(j["task"] == "dust" for j in sunday["jobs"])
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
                assert job["task"] == "dust" or cursor.weekday() != 6
                key = (job["room"], job["task"])
                if key in latest:
                    assert number - month_number(latest[key]) <= INTERVALS[job["task"]]
                latest[key] = cursor
            if plan["jobs"]:
                done_days.append(cursor)
            month_loads.append(plan["units"])
            cursor += timedelta(days=7)
        remaining = due_bundles(first.replace(day=28), started, phases, latest, TASKS, ROOMS)
        assert remaining == []
        assert all(month_number(latest[(room, "dust")]) == number for room in ROOMS)
        for room in ROOMS:
            for task, interval in INTERVALS.items():
                if month >= interval - 1:
                    assert (room, task) in latest
                    assert number - month_number(latest[(room, task)]) < interval
        all_loads.extend(month_loads)
    # The living room vacuum/mop pair alone weighs 45; all days stay <= 50.
    assert max(all_loads) <= 50


def test_overdue_work_is_carried_forward_and_empty_sunday_defers_floor_work():
    today = date(2027, 4, 25)  # Sunday, with both weekday sessions used.
    latest = {(room, "dust"): date(2027, 4, 3) for room in ROOMS}
    plan = plan_for("sunday", today, latest, [date(2027, 4, 3), date(2027, 4, 10)])
    assert plan["jobs"] == []
    assert len(plan["deferred"]) == 12
    assert all(j["overdue"] for j in plan["deferred"])
    later = plan_for("other", date(2027, 4, 26), latest, [date(2027, 4, 3), date(2027, 4, 10)])
    assert len(later["jobs"]) == 12


def test_configuration_changes_job_costs():
    tasks = {"vacuum": 3, "dust": 4, "mop": 8}
    rooms = {**ROOMS, "living": 20}
    plan = plan_for(tasks=tasks, rooms=rooms)
    for day in plan["days"]:
        assert day["units"] == sum(j["units"] for j in day["jobs"])
        assert all(j["units"] == tasks[j["task"]] * rooms[j["room"]] for j in day["jobs"])


def test_calendar_months_handle_year_and_leap_boundaries():
    latest = {(room, "dust"): date(2027, 12, 31) for room in ROOMS}
    bundles = due_bundles(date(2028, 1, 1), date(2027, 12, 1), initial_phases(ROOMS), latest, TASKS, ROOMS)
    assert sum(b.tasks == ("dust",) for b in bundles) == 6
    latest = {(room, "vacuum"): date(2028, 2, 29) for room in ROOMS}
    bundles = due_bundles(date(2028, 4, 1), date(2028, 2, 1), initial_phases(ROOMS), latest, TASKS, ROOMS)
    assert all(any(b.room == room and "vacuum" in b.tasks for b in bundles) for room in ROOMS)
