import json
import os
import secrets
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from . import db
from .scheduler import INTERVALS, ROOMS, TASKS, due_bundles, make_plan


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.getenv("CLEANING_DATABASE", str(Path(app.instance_path) / "cleaning.sqlite3")),
        TIMEZONE=os.getenv("CLEANING_TIMEZONE", "Europe/Berlin"),
        MAX_CONTENT_LENGTH=64 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(db.close_db)

    def today():
        override = app.config.get("TODAY")
        return override() if callable(override) else override or datetime.now(ZoneInfo(app.config["TIMEZONE"])).date()

    with app.app_context():
        db.init_db(today())
        app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or db.setting("secret")

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(24)
        return session["csrf"]

    @app.before_request
    def protect_forms():
        if request.method == "POST":
            token = request.form.get("csrf_token", "")
            if not token or not token.isascii() or not secrets.compare_digest(token, session.get("csrf", "")):
                abort(400, "This form has expired. Reload the page and try again.")

    @app.after_request
    def headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def common():
        return {"today": today(), "csrf_token": csrf_token, "room_names": ROOMS,
                "task_names": TASKS, "intervals": INTERVALS}

    @app.template_filter("nice_date")
    def nice_date(value):
        day = date.fromisoformat(value) if isinstance(value, str) else value
        return day.strftime("%A, %d %B %Y")

    def selected_date():
        try:
            day = date.fromisoformat(request.values.get("date", ""))
        except ValueError:
            abort(400, "Choose a valid completion date.")
        if day > today():
            abort(400, "Completed jobs cannot be recorded in the future.")
        return day

    def assignment(assignment_id):
        row = db.get_db().execute("SELECT id, plan FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not row:
            abort(404, "That cleaning plan could not be found.")
        return {"id": row["id"], **json.loads(row["plan"])}

    @app.get("/")
    def home():
        tasks, rooms = db.weights()
        current = today()
        days = db.completed_days(current)
        bundles = due_bundles(current, date.fromisoformat(db.setting("started")), json.loads(db.setting("phases")),
                              db.latest_completions(current), tasks, rooms)
        recent = db.get_db().execute("SELECT day, COUNT(*) AS count, SUM(units) AS units FROM completions GROUP BY day ORDER BY day DESC LIMIT 3").fetchall()
        return render_template("home.html", active="home", day_count=len(days), due_count=sum(len(b.tasks) for b in bundles),
                               recent=recent, last=db.last_assignment(), rooms=rooms)

    @app.route("/what-to-do", methods=["GET", "POST"])
    def what_to_do():
        if request.method == "POST":
            kind = request.form.get("kind")
            if kind not in {"sunday", "other"}:
                abort(400, "Choose Sunday or other day.")
            tasks, rooms = db.weights()
            current = today()
            plan = make_plan(current, date.fromisoformat(db.setting("started")), json.loads(db.setting("phases")),
                             db.latest_completions(current), db.completed_days(current), tasks, rooms, kind)
            with db.get_db() as conn:
                cursor = conn.execute("INSERT INTO assignments (plan) VALUES (?)", (json.dumps(plan),))
            return redirect(url_for("show_plan", plan_id=cursor.lastrowid))
        return render_template("day_choice.html", active="plan")

    @app.get("/plan/<int:plan_id>")
    def show_plan(plan_id):
        return render_template("plan.html", active="plan", plan=assignment(plan_id))

    @app.get("/what-i-did")
    def what_i_did():
        return render_template("record_date.html", active="record")

    @app.get("/record/choose")
    def record_choose():
        day = selected_date()
        return render_template("record_choice.html", active="record", day=day, last=db.last_assignment())

    def save_jobs(day, selected):
        if not selected:
            raise ValueError("Select at least one job to record.")
        jobs = set()
        for key in selected:
            parts = key.split(":")
            if len(parts) != 2 or parts[0] not in ROOMS or parts[1] not in TASKS:
                raise ValueError("One of the selected jobs is not valid.")
            jobs.add(tuple(parts))
        if day.weekday() == 6 and any(task in {"vacuum", "mop"} for _, task in jobs):
            raise ValueError("Vacuuming and mopping cannot be recorded on a Sunday. Choose another date, or select only dusting jobs.")
        # Completing a mop job always records the required same-day vacuum too.
        required = {(room, "vacuum") for room, task in jobs if task == "mop"}
        added = required - jobs
        jobs |= required
        tasks, rooms = db.weights()
        inserted = 0
        with db.get_db() as conn:
            for room, task in sorted(jobs):
                result = conn.execute("INSERT OR IGNORE INTO completions (day, room, task, units) VALUES (?, ?, ?, ?)",
                                      (day.isoformat(), room, task, rooms[room] * tasks[task]))
                inserted += result.rowcount
        flash(f"{inserted} {'job' if inserted == 1 else 'jobs'} recorded for {day.strftime('%d %B %Y')}." if inserted else "Those jobs are already recorded for this date.", "success")
        if added:
            flash("Same-day vacuuming was included with your mopping jobs.", "info")

    @app.post("/record/last")
    def record_last():
        day = selected_date()
        plan_id = request.form.get("assignment_id", type=int)
        plan = assignment(plan_id)
        try:
            save_jobs(day, [f"{j['room']}:{j['task']}" for j in plan["jobs"]])
        except ValueError as error:
            return render_template("record_choice.html", active="record", day=day, last=plan, error=str(error)), 400
        return redirect(url_for("history"))

    @app.route("/record/jobs", methods=["GET", "POST"])
    def record_jobs():
        day = selected_date()
        selected = request.form.getlist("jobs") if request.method == "POST" else []
        error = None
        if request.method == "POST":
            try:
                save_jobs(day, selected)
                return redirect(url_for("history"))
            except ValueError as exc:
                error = str(exc)
        tasks, rooms = db.weights()
        return render_template("record_jobs.html", active="record", day=day, tasks=tasks, rooms=rooms,
                               selected=selected, error=error), 400 if error else 200

    @app.route("/config", methods=["GET", "POST"])
    def config():
        tasks, rooms = db.weights()
        error = None
        values = {f"{kind}_{name}": units for kind, weights in (("task", tasks), ("room", rooms)) for name, units in weights.items()}
        if request.method == "POST":
            values = {key: request.form.get(key, "") for key in values}
            try:
                parsed = {key: int(value) for key, value in values.items()}
                if any(value < 1 or value > 1000 for value in parsed.values()):
                    raise ValueError
            except ValueError:
                error = "Enter a whole number from 1 to 1,000 for every work and room size value."
            else:
                with db.get_db() as conn:
                    for key, value in parsed.items():
                        kind, name = key.split("_", 1)
                        conn.execute("UPDATE weights SET units = ? WHERE kind = ? AND name = ?", (value, kind, name))
                flash("Your work and room size units have been saved. New plans will use these values.", "success")
                return redirect(url_for("config"))
        return render_template("config.html", active="config", values=values, error=error), 400 if error else 200

    @app.get("/history")
    def history():
        rows = db.get_db().execute("SELECT * FROM completions ORDER BY day DESC, room, CASE task WHEN 'dust' THEN 0 WHEN 'vacuum' THEN 1 ELSE 2 END").fetchall()
        grouped = {}
        for row in rows:
            grouped.setdefault(row["day"], []).append(dict(row))
        return render_template("history.html", active="history", history=grouped, job_count=len(rows))

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def request_error(error):
        return render_template("error.html", error=error.description, code=error.code), error.code

    return app
