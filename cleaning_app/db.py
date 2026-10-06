"""SQLite persistence. Each request gets its own connection."""

import json
import secrets
import sqlite3
from datetime import date

from flask import current_app, g

from .scheduler import ROOMS, TASKS, initial_phases


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(today):
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS weights (
            kind TEXT NOT NULL, name TEXT NOT NULL, units INTEGER NOT NULL CHECK(units > 0),
            PRIMARY KEY (kind, name)
        );
        CREATE TABLE IF NOT EXISTS completions (
            id INTEGER PRIMARY KEY, day TEXT NOT NULL, room TEXT NOT NULL,
            task TEXT NOT NULL, units INTEGER NOT NULL,
            UNIQUE (day, room, task)
        );
        CREATE INDEX IF NOT EXISTS completions_day ON completions(day DESC);
        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            plan TEXT NOT NULL
        );
    """)
    with db:
        for key, value in {"started": today.isoformat(), "phases": json.dumps(initial_phases(ROOMS)),
                           "secret": secrets.token_hex(32)}.items():
            db.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (key, value))
        for kind, weights in (("task", TASKS), ("room", ROOMS)):
            db.executemany("INSERT OR IGNORE INTO weights VALUES (?, ?, ?)",
                           [(kind, name, units) for name, units in weights.items()])


def setting(key):
    return get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()["value"]


def weights():
    rows = get_db().execute("SELECT * FROM weights").fetchall()
    values = {(r["kind"], r["name"]): r["units"] for r in rows}
    return ({name: values[("task", name)] for name in TASKS},
            {name: values[("room", name)] for name in ROOMS})


def latest_completions(today):
    rows = get_db().execute("SELECT room, task, MAX(day) AS day FROM completions WHERE day <= ? GROUP BY room, task",
                            (today.isoformat(),)).fetchall()
    return {(r["room"], r["task"]): date.fromisoformat(r["day"]) for r in rows}


def completed_days(today):
    return [date.fromisoformat(r["day"]) for r in get_db().execute(
        "SELECT DISTINCT day FROM completions WHERE day >= ? AND day <= ?",
        (today.replace(day=1).isoformat(), today.isoformat()))]


def last_assignment():
    row = get_db().execute("SELECT id, plan FROM assignments ORDER BY id DESC LIMIT 1").fetchone()
    return {"id": row["id"], **json.loads(row["plan"])} if row else None
