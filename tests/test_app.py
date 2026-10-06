from datetime import date

import pytest

from cleaning_app import create_app, db
from cleaning_app.scheduler import ROOMS, TASKS


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "cleaning.sqlite3"), "TODAY": date(2026, 10, 26)})


@pytest.fixture
def client(app):
    return app.test_client()


def post(client, path, data=None, follow_redirects=True):
    client.get("/what-to-do")
    with client.session_transaction() as session:
        token = session["csrf"]
    return client.post(path, data={"csrf_token": token, **(data or {})}, follow_redirects=follow_redirects)


def rows(app):
    with app.app_context():
        return [dict(row) for row in db.get_db().execute("SELECT * FROM completions ORDER BY day DESC")]


@pytest.mark.parametrize("path", ["/", "/what-to-do", "/what-i-did", "/config", "/history",
                                  "/record/choose?date=2026-10-26", "/record/jobs?date=2026-10-26"])
def test_pages_load(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert b"Cleaning App" in response.data
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_default_date_and_all_18_job_choices(client):
    assert b'value="2026-10-26"' in client.get("/what-i-did").data
    response = client.get("/record/jobs?date=2026-10-26")
    assert response.data.count(b'type="checkbox"') == 18


def test_assignment_recording_and_duplicate_submission(app, client):
    response = post(client, "/what-to-do", {"kind": "other"})
    assert response.status_code == 200
    assert b"Your cleaning list" in response.data
    assert rows(app) == []
    with app.app_context():
        plan = db.last_assignment()
    response = post(client, "/record/last", {"date": "2026-10-26", "assignment_id": plan["id"]})
    assert response.status_code == 200
    assert len(rows(app)) == len(plan["jobs"])
    response = post(client, "/record/last", {"date": "2026-10-26", "assignment_id": plan["id"]})
    assert b"already recorded" in response.data
    assert len(rows(app)) == len(plan["jobs"])


def test_mop_adds_same_day_vacuum_and_backdating_does_not_regress_latest(app, client):
    response = post(client, "/record/jobs", {"date": "2026-10-26", "jobs": ["living:mop", "bed:dust"]})
    assert response.status_code == 200
    assert {(r["room"], r["task"]) for r in rows(app)} == {("living", "mop"), ("living", "vacuum"), ("bed", "dust")}
    post(client, "/record/jobs", {"date": "2026-09-25", "jobs": ["living:mop"]})
    with app.app_context():
        assert db.latest_completions(date(2026, 10, 26))[("living", "mop")] == date(2026, 10, 26)
    history = client.get("/history").data
    assert history.index(b"26 October 2026") < history.index(b"25 September 2026")


@pytest.mark.parametrize("jobs", [["living:vacuum"], ["living:mop"], ["bed:dust", "bath:mop"]])
def test_sunday_floor_work_rejected_atomically(app, client, jobs):
    response = post(client, "/record/jobs", {"date": "2026-10-25", "jobs": jobs})
    assert response.status_code == 400
    assert b"cannot be recorded on a Sunday" in response.data
    assert rows(app) == []


def test_sunday_dust_accepted(app, client):
    response = post(client, "/record/jobs", {"date": "2026-10-25", "jobs": ["living:dust", "guest:dust"]})
    assert response.status_code == 200
    assert len(rows(app)) == 2


def test_stale_assigned_floor_plan_cannot_bypass_sunday_rule(app, client):
    post(client, "/record/jobs", {"date": "2026-10-24", "jobs": ["bed:dust"]})
    post(client, "/what-to-do", {"kind": "other"})
    with app.app_context():
        plan = db.last_assignment()
    assert any(job["task"] == "mop" for job in plan["jobs"])
    response = post(client, "/record/last", {"date": "2026-10-25", "assignment_id": plan["id"]})
    assert response.status_code == 400
    assert len(rows(app)) == 1


@pytest.mark.parametrize("day", ["", "invalid", "2026-02-30", "2026-10-27"])
def test_invalid_and_future_dates_rejected(client, day):
    assert client.get("/record/choose", query_string={"date": day}).status_code == 400
    assert post(client, "/record/jobs", {"date": day, "jobs": ["bath:dust"]}).status_code == 400


@pytest.mark.parametrize("jobs", [[], ["attic:dust"], ["bed:polish"], ["bed:dust:extra"]])
def test_invalid_selection_rejected_atomically(app, client, jobs):
    assert post(client, "/record/jobs", {"date": "2026-10-26", "jobs": jobs}).status_code == 400
    assert rows(app) == []


def test_config_persists_and_history_keeps_original_units(app, client):
    post(client, "/record/jobs", {"date": "2026-10-26", "jobs": ["living:dust"]})
    values = {**{f"task_{k}": v for k, v in TASKS.items()}, **{f"room_{k}": v for k, v in ROOMS.items()}}
    values["task_dust"] = "8"
    assert post(client, "/config", values).status_code == 200
    assert rows(app)[0]["units"] == 18
    reopened = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "TODAY": date(2026, 10, 26)})
    with reopened.app_context():
        assert db.weights()[0]["dust"] == 8
        assert db.get_db().execute("SELECT COUNT(*) FROM completions").fetchone()[0] == 1


@pytest.mark.parametrize("bad", ["0", "-1", "2.5", "no", "1001", ""])
def test_invalid_config_does_not_partially_save(app, client, bad):
    values = {**{f"task_{k}": v for k, v in TASKS.items()}, **{f"room_{k}": v for k, v in ROOMS.items()}}
    values.update(task_dust="25", room_living=bad)
    assert post(client, "/config", values).status_code == 400
    with app.app_context():
        assert db.weights() == (TASKS, ROOMS)


def test_csrf_and_unknown_routes(client):
    assert client.post("/what-to-do", data={"kind": "other"}).status_code == 400
    assert client.post("/what-to-do", data={"kind": "other", "csrf_token": "\u2603"}).status_code == 400
    assert post(client, "/what-to-do", {"kind": "unknown"}).status_code == 400
    assert client.get("/plan/999").status_code == 404
    assert client.get("/missing").status_code == 404


def test_saved_plan_and_secret_survive_restart(app, client):
    post(client, "/what-to-do", {"kind": "sunday"})
    with app.app_context():
        old_plan = db.last_assignment()
    reopened = create_app({"TESTING": True, "DATABASE": app.config["DATABASE"], "TODAY": date(2026, 10, 26)})
    assert reopened.config["SECRET_KEY"] == app.config["SECRET_KEY"]
    with reopened.app_context():
        assert db.last_assignment() == old_plan
