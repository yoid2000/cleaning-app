"""Calendar-month scheduling with an exact, small workload partition search.

Mopping always includes vacuuming. Vacuuming on its own is allowed, since
two-month vacuum and three-month mop intervals cannot otherwise coexist.
"""

from dataclasses import dataclass
from datetime import date
from itertools import product

TASKS = {"vacuum": 1, "dust": 2, "mop": 4}
ROOMS = {"living": 9, "guest": 7, "bed": 5, "hall": 3, "bath": 3, "kitchen": 3}
INTERVALS = {"vacuum": 2, "dust": 1, "mop": 3}


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
        for task, interval in INTERVALS.items():
            previous = latest.get((room, task))
            offset = 0 if task == "dust" else phases[room] if task == "mop" else min(phases[room], 1)
            due[task] = month_number(previous) + interval if previous else start + offset
        if due["dust"] <= current:
            result.append(Bundle(room, ("dust",), size * tasks["dust"], due["dust"]))
        if due["mop"] <= current:
            result.append(Bundle(room, ("vacuum", "mop"), size * (tasks["vacuum"] + tasks["mop"]), min(due["mop"], due["vacuum"])))
        elif due["vacuum"] <= current:
            result.append(Bundle(room, ("vacuum",), size * tasks["vacuum"], due["vacuum"]))
    return sorted(result, key=lambda b: (-b.units, b.due, b.room, b.tasks))


def make_plan(today, started, phases, latest, completed_days, tasks, rooms, kind):
    """Divide all due jobs over this month’s remaining cleaning days.

    At most twelve bundles exist, so an exhaustive partition with pruning is
    cheap. Minimize squared daily workloads; break ties in favor of older work
    on the requested day. The remaining identical weekdays are interchangeable.
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
    loads = [0] * len(slots)
    groups = [[] for _ in slots]
    best_score = None
    best_groups = None

    def search(index, priority):
        nonlocal best_score, best_groups
        if best_score and sum(n * n for n in loads) > best_score[0]:
            return
        if index == len(available):
            score = (sum(n * n for n in loads), -priority, -loads[0])
            if best_score is None or score < best_score:
                best_score = score
                best_groups = [g.copy() for g in groups]
            return
        bundle = available[index]
        seen = set()
        for slot in sorted(range(len(slots)), key=lambda i: (loads[i], i)):
            if bundle.floor and slots[slot] == "sunday":
                continue
            # Never merge the requested day with a future day for tie-breaking.
            signature = (slots[slot], loads[slot], slot == 0)
            if signature in seen:
                continue
            seen.add(signature)
            groups[slot].append(bundle)
            loads[slot] += bundle.units
            search(index + 1, priority + ((current - bundle.due + 1) * len(bundle.tasks) if slot == 0 else 0))
            loads[slot] -= bundle.units
            groups[slot].pop()

    search(0, 0)

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
            "completed_days": len(days), "created_date": today.isoformat()}
