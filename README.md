# Cleaning App

A standalone Python web app that plans household cleaning, records completed jobs,
and keeps a dated history. Flask handles the application and Waitress listens for
HTTP requests directly; Apache, Nginx, and a separate database server are not needed.

## Run

Requires Python 3.10 or newer.

On Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python app.py
```

On Linux or macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Open **http://127.0.0.1:8000**. Stop the server with Ctrl+C.

To listen on a different port or accept connections from your home network:

```powershell
.\.venv\Scripts\python app.py --host 0.0.0.0 --port 8080
```

Other devices can then use `http://<server-IP>:8080` if the server's firewall allows
it. This is a single-household app without account authentication, intended for a
trusted private network. The default binds only to the local computer.

## Using the app

- **What to do:** choose **Sunday** or **Other day**. The app saves a balanced set
  of jobs for your next cleaning day. Viewing or refreshing a plan does not complete
  jobs or consume a cleaning day.
- **What I did:** choose a date (today by default), then either record the last
  assigned jobs or select from the complete 18-job menu. You can record any subset
  of a plan through the menu. Selecting mopping includes same-day vacuuming.
- **Config:** change task work and room size units. New plans use the new values;
  history retains the effort recorded at completion.
- **History:** all recorded jobs grouped by date, newest first. Re-submitting a
  job for the same room, task, and date does not create duplicates.

## Scheduling rules

| Task | Work units | Frequency |
| --- | ---: | --- |
| Vacuum | 1 | Every 2 calendar months, plus every mop day |
| Dust | 2 | Every calendar month |
| Mop | 4 | Every 3 calendar months |

| Room | Size units |
| --- | ---: |
| Living | 9 |
| Guest | 7 |
| Bed | 5 |
| Hall | 3 |
| Bath | 3 |
| Kitchen | 3 |

Job difficulty is **room size × task work**.

The different vacuum/mop intervals require interpreting the same-day rule as
**every mop must have a same-day vacuum**; vacuum-only sessions are allowed.
Otherwise, the two requested intervals would be incompatible. Vacuuming may happen
more often than every other month to accompany mopping. Neither floor task is
assigned or accepted on a Sunday.

Frequencies use **calendar months**, not a fixed number of days. For example,
vacuuming in October makes the next vacuum due in December; mopping in October
makes the next mop due in January. A job is eligible from the start of its due
month. It can therefore be completed early or late in that month. This matches the
three-days-per-month routine without requiring fixed dates for cleaning days.

On a fresh installation, dusting is due for all rooms in the first month. The
rooms are split into three cohorts with balanced total size (9, 10, and 11 with
the defaults). Their first mops are due in months one, two, and three. Every room's
first vacuum is due within the first two months. This starts a sustainable rhythm
without treating every unrecorded job as overdue immediately. Existing cleaning
can be entered through **What I did**; actual completion history takes precedence
over the initial schedule.

Each plan allocates all due work across the remaining days of the monthly target:
one Sunday and two non-Sundays. A cleaning day is a distinct date with at least one
recorded job. Vacuum/mop pairs are indivisible, and Sunday can only receive dusting.
The scheduler searches the valid allocations and minimizes the sum of squared daily
workloads. Ties favor older jobs on the requested day. Large indivisible room jobs
can prevent perfectly equal daily workloads.

After work is recorded, the next plan recalculates from actual history. Backdated
records do not replace newer completions. Unfinished work remains due; overdue
work carries into future months. If the chosen day is a Sunday and the month's
two non-Sundays are already used, outstanding floor jobs are explicitly flagged
as requiring an additional non-Sunday day. If you miss sessions, completing all
frequency targets can require extra work or an extra day.

## Storage and server settings

SQLite data, saved assignments, configuration, and the persistent session secret
are stored in **`instance/cleaning.sqlite3`** by default. This directory is excluded
from Git. To back up the household data, stop the app and copy this file. Restarting
the app preserves everything.

Optional environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLEANING_HOST` | `127.0.0.1` | Listening address; `--host` takes precedence |
| `CLEANING_PORT` | `8000` | Listening port; `--port` takes precedence |
| `CLEANING_DATABASE` | `instance/cleaning.sqlite3` in this project | SQLite file path |
| `CLEANING_TIMEZONE` | `Europe/Berlin` | Timezone used for today's date |

All main workflows work without JavaScript. JavaScript adds immediate selection
totals and checks the vacuum box when mopping is selected. The server independently
validates dates, jobs, Sunday restrictions, and configuration values. Forms include
CSRF protection.

## Tests

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
```

The suite covers the application workflows, SQLite persistence, duplicate and
backdated entries, validation, Sunday rules, paired floor jobs, optimal workload
partitioning, and two-year schedule simulations for every ordering of the three
monthly day types. With the default settings and regular completion, those
simulations meet all calendar-month frequencies in three days per month.
