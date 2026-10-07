#!/usr/bin/env bash
# Update the systemd installation described in linux-install.dev.
set -Eeuo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${CLEANING_APP_DIR:-/opt/cleaning-app}"
SERVICE="${CLEANING_SERVICE:-cleaning-app.service}"
HEALTH_URL="${CLEANING_HEALTH_URL:-http://127.0.0.1:8123/}"
service_stopped=0

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

cleanup() {
    local result=$?
    if (( service_stopped )); then
        printf 'Update interrupted. Attempting to start %s again.\n' "$SERVICE" >&2
        sudo systemctl start "$SERVICE" || true
    fi
    if (( result != 0 )); then
        printf 'Update did not complete. Check: sudo journalctl -u %s -n 100 --no-pager\n' "$SERVICE" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(( EUID != 0 )) || fail "Run this script as your normal Linux user, without sudo. It requests sudo when needed."
for command in git sudo systemctl curl install cp chmod; do
    command -v "$command" >/dev/null || fail "Required command is missing: $command"
done
[[ "$APP_DIR" = /* && "$APP_DIR" != / ]] || fail "CLEANING_APP_DIR must be an absolute application directory."
[[ -x "$APP_DIR/.venv/bin/python" && -f "$APP_DIR/app.py" && -d "$APP_DIR/cleaning_app" ]] ||
    fail "No existing installation found at $APP_DIR. Follow linux-install.dev first."

cd -- "$SOURCE_DIR"
git rev-parse --is-inside-work-tree >/dev/null
[[ -z "$(git status --porcelain)" ]] || fail "The source checkout has local changes. Commit or move them before updating."
sudo -v
sudo systemctl is-active --quiet "$SERVICE" || fail "The service $SERVICE is not running."

printf 'Pulling the latest code from the current branch...\n'
git pull --ff-only
[[ -f app.py && -f requirements.txt && -d cleaning_app ]] || fail "The checkout is missing application files."

# Stop before replacing code or packages so requests cannot use a partial update.
# Only application files are copied; /var/lib/cleaning-app is left in place.
printf 'Stopping %s and installing the update...\n' "$SERVICE"
service_stopped=1
sudo systemctl stop "$SERVICE"
sudo install -m 0644 app.py requirements.txt "$APP_DIR/"
sudo cp -R cleaning_app/. "$APP_DIR/cleaning_app/"
sudo chmod -R a+rX "$APP_DIR/cleaning_app"
sudo "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

printf 'Restarting %s...\n' "$SERVICE"
sudo systemctl restart "$SERVICE"
service_stopped=0

# Give the server time to bind its port, then require both systemd and HTTP health.
for (( attempt=1; attempt<=15; attempt++ )); do
    if sudo systemctl is-active --quiet "$SERVICE" &&
        curl --fail --silent --output /dev/null --connect-timeout 2 --max-time 2 "$HEALTH_URL"; then
        printf 'Update complete. %s is running and responding at %s\n' "$SERVICE" "$HEALTH_URL"
        exit 0
    fi
    sleep 1
done

sudo systemctl status "$SERVICE" --no-pager || true
fail "The restarted app did not respond successfully at $HEALTH_URL."
