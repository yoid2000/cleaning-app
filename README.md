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

For Linux installation with automatic startup after reboot, follow
[linux-install.dev](linux-install.dev).
For an existing installation from that guide, run
`bash ~/src/cleaning-app/update-linux.sh` as your normal Linux user to pull updates,
install dependencies, and restart the service. See the guide's update section for
first-time use and custom settings.

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
  assigned jobs or select from the complete 19-job menu. You can record any subset
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
| Mop | 4 | Kitchen every calendar month; other rooms every 3 calendar months |
| Shower | 60 total | Every calendar month, on Sunday or any other day |

| Room | Size units |
| --- | ---: |
| Living | 9 |
| Guest | 7 |
| Bed | 5 |
| Hall | 3 |
| Bath | 3 |
| Kitchen | 3 |

Job difficulty is **room size × task work** for vacuuming, dusting, and mopping.
**Shower** is a single job under **Bath** and takes **60 total work units** by
default, independent of room size. Its total work units can be changed in Config.

The different vacuum/mop intervals require interpreting the same-day rule as
**every mop must have a same-day vacuum**; vacuum-only sessions are allowed.
Otherwise, the two requested intervals would be incompatible. Vacuuming may happen
more often than every other month to accompany mopping. Neither floor task is
assigned or accepted on a Sunday.

Frequencies use **calendar months**, not a fixed number of days. For example,
vacuuming in October makes the next vacuum due in December; mopping in October
makes the next mop due in January for other rooms, or November for the kitchen.
A job is eligible from the start of its due
month. It can therefore be completed early or late in that month. This matches the
three-days-per-month routine without requiring fixed dates for cleaning days.

On a fresh installation, dusting is due for all rooms and shower cleaning is due
in the first month. The
rooms are split into three cohorts with balanced total size (9, 10, and 11 with
the defaults). Other rooms' first mops are due in months one, two, and three.
Kitchen mopping is due in the first month and every month thereafter. Every room's
first vacuum is due within the first two months. This starts a sustainable rhythm
without treating every unrecorded job as overdue immediately. Existing cleaning
can be entered through **What I did**; actual completion history takes precedence
over the initial schedule.

Each plan balances due work across the remaining days of the monthly target:
one Sunday and two non-Sundays. A cleaning day is a distinct date with at least one
recorded job. Vacuum/mop pairs are indivisible, and Sunday can receive dusting
and shower cleaning.
The scheduler searches the valid allocations and minimizes the sum of squared daily
workloads. Ties favor older jobs on the requested day. A session's workload is
limited to the largest balanced session in a simulated year of regular cleaning,
using the current room sizes, task weights, and starting cohorts (66 units with
the defaults). Large indivisible room jobs can prevent perfectly equal workloads.

After work is recorded, the next plan recalculates from actual history. Backdated
records do not replace newer completions. Unfinished work remains due; overdue
work carries into future months. Missing a week lets the schedule slip; it does
not increase the usual workload to meet a calendar deadline. If all due work
cannot fit within the normal workload, older jobs take priority and excess jobs
carry forward to later sessions, even beyond the current month. Floor jobs also
carry forward when no non-Sunday slot is available. The next due month is based
on actual completion, so completing a job late shifts its next occurrence.

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
.\.venv\Scripts\python -m pytest tests -q
```

The suite covers the application workflows, SQLite persistence, duplicate and
backdated entries, validation, Sunday rules, paired floor jobs, optimal workload
partitioning, monthly kitchen mopping and shower cleaning, shower's total work
units and Sunday eligibility, existing database upgrades, missed sessions without increased workload,
and two-year schedule simulations for every ordering of the three
monthly day types. With the default settings and regular completion, those
simulations meet all calendar-month frequencies in three days per month.
