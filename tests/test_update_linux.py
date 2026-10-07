"""Exercise deployment ordering and failures without touching a real service."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


BASH = shutil.which("bash")
if BASH is None and os.name == "nt":
    candidate = Path("C:/Program Files/Git/bin/bash.exe")
    if candidate.exists():
        BASH = str(candidate)
pytestmark = pytest.mark.skipif(BASH is None, reason="Bash is not installed")
SCRIPT = Path(__file__).resolve().parents[1] / "update-linux.sh"


def shell_path(path):
    value = path.resolve().as_posix()
    return f"/{value[0].lower()}{value[2:]}" if os.name == "nt" else value


def executable(path, contents):
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + contents, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.fixture
def updater(tmp_path):
    source = tmp_path / "source checkout"
    installed = tmp_path / "installed app"
    fake_bin = tmp_path / "bin"
    log = tmp_path / "commands.log"
    for directory in (source / "cleaning_app", installed / "cleaning_app", installed / ".venv/bin", fake_bin):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SCRIPT, source / SCRIPT.name)
    (source / "app.py").write_text("new server\n", encoding="utf-8")
    (source / "requirements.txt").write_text("new dependencies\n", encoding="utf-8")
    (source / "cleaning_app/__init__.py").write_text("new application\n", encoding="utf-8")
    (installed / "app.py").write_text("old server\n", encoding="utf-8")
    executable(fake_bin / "git", """
printf 'git %s\n' "$*" >> "$UPDATE_TEST_LOG"
case "$1" in
    status) printf '%s' "${UPDATE_TEST_DIRTY:-}" ;;
    pull) exit "${UPDATE_TEST_PULL_RESULT:-0}" ;;
esac
""")
    executable(fake_bin / "sudo", """
if [[ "$1" == -v ]]; then exit 0; fi
exec "$@"
""")
    executable(fake_bin / "systemctl", """
printf 'systemctl %s\n' "$*" >> "$UPDATE_TEST_LOG"
""")
    executable(installed / ".venv/bin/python", """
printf 'python %s\n' "$*" >> "$UPDATE_TEST_LOG"
exit "${UPDATE_TEST_PIP_RESULT:-0}"
""")
    executable(fake_bin / "curl", """
printf 'curl\n' >> "$UPDATE_TEST_LOG"
exit "${UPDATE_TEST_HEALTH_RESULT:-0}"
""")
    executable(fake_bin / "sleep", "exit 0\n")
    env = {**os.environ, "UPDATE_TEST_BIN": shell_path(fake_bin),
           "CLEANING_APP_DIR": shell_path(installed), "UPDATE_TEST_LOG": shell_path(log)}

    def run(**overrides):
        result = subprocess.run([BASH, "-c", 'export PATH="$UPDATE_TEST_BIN:$PATH"; source "$1"',
                                 "update-test", shell_path(source / SCRIPT.name)],
                                env={**env, **overrides}, capture_output=True, text=True, timeout=30)
        if "Run this script as your normal Linux user" in result.stderr:
            pytest.skip("Deployment smoke tests require a non-root user")
        assert log.exists(), (result.stdout, result.stderr)
        return result, log.read_text(encoding="utf-8").splitlines()

    return run, installed


def test_update_copies_files_installs_dependencies_and_restarts_in_order(updater):
    run, installed = updater
    result, commands = run()
    assert result.returncode == 0, result.stderr
    assert "Update complete" in result.stdout
    assert (installed / "app.py").read_text() == "new server\n"
    assert (installed / "cleaning_app/__init__.py").read_text() == "new application\n"
    pull = commands.index("git pull --ff-only")
    stop = commands.index("systemctl stop cleaning-app.service")
    pip = next(i for i, command in enumerate(commands) if command.startswith("python -m pip install -r "))
    restart = commands.index("systemctl restart cleaning-app.service")
    assert pull < stop < pip < restart < commands.index("curl")


@pytest.mark.parametrize("failure", [{"UPDATE_TEST_PULL_RESULT": "1"}, {"UPDATE_TEST_DIRTY": " M app.py"}])
def test_source_failure_leaves_running_app_untouched(updater, failure):
    run, installed = updater
    result, commands = run(**failure)
    assert result.returncode != 0
    assert not any(command.startswith("systemctl stop") for command in commands)
    assert (installed / "app.py").read_text() == "old server\n"


def test_dependency_failure_attempts_to_start_service_again(updater):
    run, _ = updater
    result, commands = run(UPDATE_TEST_PIP_RESULT="1")
    assert result.returncode != 0
    assert "systemctl start cleaning-app.service" in commands
    assert "systemctl restart cleaning-app.service" not in commands
    assert "Update did not complete" in result.stderr


def test_failed_health_check_reports_failure_after_restart(updater):
    run, _ = updater
    result, commands = run(UPDATE_TEST_HEALTH_RESULT="22")
    assert result.returncode != 0
    assert "systemctl restart cleaning-app.service" in commands
    assert commands.count("curl") == 15
    assert "systemctl status cleaning-app.service --no-pager" in commands
    assert "did not respond successfully" in result.stderr
