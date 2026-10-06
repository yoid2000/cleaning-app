"""Calendar-month scheduling with an exact, small workload partition search.

Mopping always includes vacuuming. Vacuuming on its own is allowed, since
two-month vacuum and three-month mop intervals cannot otherwise coexist.
"""

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from itertools import product

TASKS = {"vacuum": 1, "dust": 2, "mop": 4}
ROOMS = {"living": 9, "guest": 7, "bed": 5, "hall": 3, "bath": 3, "kitchen": 3}
INTERVALS = {"vacuum": 2, "dust": 1, "mop": 3}


def task_interval(room, task):
    return 1 if (room, task) == ("kitchen", "mop") else INTERVALS[task]


def month_number(day: date) -> int:
    return day.year * 12 + day.month - 1


def initial_phases(rooms: dict) -> dict:
    """Split the six rooms into three balanced, permanent starting cohorts."""
    names = list(rooms)
    best = None
    for phases in product(range(3), repeat=len(names) - 1):
        phases = (0,) + phases  # Equivalent group permutations need not be searched.
        loads = [sum(rooms[r] for r, p in zip(names, phases) if p == i) for i in range(3)]
        score = (sum(n * n for n in loads), phases)
        if best is None or score < best[0]:
            best = (score, dict(zip(names, phases)))
    return best[1]


@dataclass(frozen=True)
class Bundle:
    room: str
    tasks: tuple[str, ...]
    units: int
    due: int

    @property
    def floor(self):
        return "vacuum" in self.tasks


def due_bundles(today, started, phases, latest, tasks, rooms):
    current = month_number(today)
    start = month_number(started)
    result = []
    for room, size in rooms.items():
        due = {}
        for task in INTERVALS:
            interval = task_interval(room, task)
            previous = latest.get((room, task))
            offset = 0 if task == "dust" else phases[room] if task == "mop" else min(phases[room], 1)
            if (room, task) == ("kitchen", "mop"):
                offset = 0
            due[task] = month_number(previous) + interval if previous else start + offset
        if due["dust"] <= current:
            result.append(Bundle(room, ("dust",), size * tasks["dust"], due["dust"]))
        if due["mop"] <= current:
            result.append(Bundle(room, ("vacuum", "mop"), size * (tasks["vacuum"] + tasks["mop"]), min(due["mop"], due["vacuum"])))
        elif due["vacuum"] <= current:
            result.append(Bundle(room, ("vacuum",), size * tasks["vacuum"], due["vacuum"]))
    return sorted(result, key=lambda b: (-b.units, b.due, b.room, b.tasks))


def partition(bundles, slots, current, limit=None):
    """Balance bundles; with a limit, carry excess work into later sessions."""
    loads = [0] * len(slots)
    groups = [[] for _ in slots]
    best_score = None
    best_groups = None

    best_deferred = None
    memo = {}

    def search(index, priority, carried, age, units):
        nonlocal best_score, best_groups, best_deferred
        if limit is None and best_score and sum(n * n for n in loads) > best_score[0]:
            return
        if limit is not None:
            state = (index, tuple(loads))
            value = (age, units, priority)
            if state in memo and memo[state] >= value:
                return
            memo[state] = value
        if index == len(bundles):
            score = (sum(n * n for n in loads), -priority, -loads[0])
            if limit is not None:
                score = (-age, -units) + score
            if best_score is None or score < best_score:
                best_score = score
                best_groups = [g.copy() for g in groups]
                best_deferred = carried.copy()
            return
        bundle = bundles[index]
        urgency = (current - bundle.due + 1) * len(bundle.tasks)
        seen = set()
        for slot in sorted(range(len(slots)), key=lambda i: (loads[i], i)):
            if bundle.floor and slots[slot] == "sunday":
                continue
            if limit is not None and loads[slot] + bundle.units > limit:
                continue
            # Never merge the requested day with a future day for tie-breaking.
            signature = (slots[slot], loads[slot], slot == 0)
            if signature in seen:
                continue
            seen.add(signature)
            groups[slot].append(bundle)
            loads[slot] += bundle.units
            search(index + 1, priority + (urgency if slot == 0 else 0), carried,
                   age + urgency, units + bundle.units)
            loads[slot] -= bundle.units
            groups[slot].pop()
        if limit is not None:
            search(index + 1, priority, carried + [bundle], age, units)

    search(0, 0, [], 0, 0)
    return best_groups, best_deferred


@lru_cache(maxsize=32)
def _usual_workload(phases_items, tasks_items, rooms_items):
    """Find the largest balanced session in a regular, on-time year.

    Use current weights and the household's cohorts, so the limit follows config
    changes and always accommodates an indivisible vacuum/mop pair.
    """
    phases, tasks, rooms = map(dict, (phases_items, tasks_items, rooms_items))
    started = date(2000, 1, 1)
    latest = {}
    limit = 0
    for month in range(1, 13):
        day = date(2000, month, 1)
        bundles = due_bundles(day, started, phases, latest, tasks, rooms)
        groups, _ = partition(bundles, ["other", "sunday", "other"], month_number(day))
        limit = max(limit, *(sum(b.units for b in group) for group in groups))
        for bundle in bundles:
            for task in bundle.tasks:
                latest[bundle.room, task] = day
    return limit


def make_plan(today, started, phases, latest, completed_days, tasks, rooms, kind):
    """Balance due work without making sessions heavier to catch up.

    Calendar months determine eligibility. Unfinished work retains its priority,
    but work exceeding a usual session slips to later cleaning days.
    Merely requesting a plan never counts as completing a cleaning day.
    """
    if kind not in {"sunday", "other"}:
        raise ValueError("Choose Sunday or other day.")
    current = month_number(today)
    days = {d for d in completed_days if month_number(d) == current and d <= today}
    sundays = sum(d.weekday() == 6 for d in days)
    others = len(days) - sundays
    slots = [kind]
    slots += ["sunday"] * max(0, 1 - sundays - (kind == "sunday"))
    slots += ["other"] * max(0, 2 - others - (kind == "other"))
    bundles = due_bundles(today, started, phases, latest, tasks, rooms)
    available = [b for b in bundles if not b.floor or "other" in slots]
    deferred = [b for b in bundles if b not in available]
    limit = _usual_workload(tuple(phases.items()), tuple(tasks.items()), tuple(rooms.items()))
    best_groups, _ = partition(available, slots, current)
    if any(sum(b.units for b in group) > limit for group in best_groups):
        best_groups, carried = partition(available, slots, current, limit)
        deferred += carried

    def jobs_for(group):
        return [
            {"room": b.room, "task": task, "units": rooms[b.room] * tasks[task],
             "overdue": b.due < current}
            for b in sorted(group, key=lambda b: (b.room, b.tasks)) for task in b.tasks
        ]

    planned = [{"kind": slot, "jobs": jobs_for(group), "units": sum(b.units for b in group)}
               for slot, group in zip(slots, best_groups)]
    return {"kind": kind, "month": today.strftime("%B %Y"), "jobs": planned[0]["jobs"],
            "units": planned[0]["units"], "days": planned, "deferred": jobs_for(deferred),
            "completed_days": len(days), "created_date": today.isoformat(),
            "workload_limit": limit}
