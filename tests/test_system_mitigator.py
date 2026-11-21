"""roles/systemd/files/system-mitigator.py: throttle and journald-crash-loop detection.

The script runs its polling loop at import time and reads absolute sysfs paths,
so each test loads a fresh copy with sleep, subprocess, the clock and glob
swapped for fakes: sysfs lives under tmp_path and the loop stops after one pass.
"""
import glob as real_glob
import importlib.util
import logging
import subprocess
import time
import types
from pathlib import Path

import pytest

from conftest import REPO

SCRIPT = REPO / "roles" / "systemd" / "files" / "system-mitigator.py"
_REAL_GLOB = real_glob.glob
START = 100_000.0  # far past the 900s / 300s rate-limit windows


class Env:
    """Handle on one loaded copy of the script plus its fakes."""

    def __init__(self, sysfs):
        self.sysfs = sysfs
        self.now = START
        self.journal = []  # NRestarts readings consumed in order; an Exception is raised
        self.calls = []  # argv of every subprocess.run
        self.notifications = []  # (title, message, critical)
        self.mod = None

    def _run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == "notify-send":
            return subprocess.CompletedProcess(argv, 0)
        item = self.journal.pop(0)
        if isinstance(item, Exception):
            raise item
        return subprocess.CompletedProcess(argv, 0, stdout=item, stderr="")

    def _glob(self, pattern):
        # /sys/... -> <tmp>/sys/...
        return _REAL_GLOB(str(self.sysfs) + pattern.removeprefix("/sys"))

    def cpu(self, n, cur, min_=400_000, with_min=True):
        d = self.sysfs / "devices" / "system" / "cpu" / f"cpu{n}" / "cpufreq"
        d.mkdir(parents=True, exist_ok=True)
        (d / "scaling_cur_freq").write_text(f"{cur}\n")
        if with_min:
            (d / "scaling_min_freq").write_text(f"{min_}\n")

    def zone(self, n, kind, temp):
        d = self.sysfs / "class" / "thermal" / f"thermal_zone{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "type").write_text(f"{kind}\n")
        (d / "temp").write_text(f"{temp}\n")

    def notify_calls(self):
        return [c for c in self.calls if c[0] == "notify-send"]


@pytest.fixture
def load(tmp_path, monkeypatch):
    """load(initial_journal=...) -> Env with the script imported and one loop pass done."""
    root = logging.getLogger()
    before = list(root.handlers)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    def _load(initial_journal=("NRestarts=0\n",)):
        env = Env(tmp_path / "sys")
        env.journal = list(initial_journal)

        def stop(_seconds):
            raise KeyboardInterrupt

        with monkeypatch.context() as m:
            m.setattr(subprocess, "run", env._run)
            m.setattr(real_glob, "glob", env._glob)
            m.setattr(time, "sleep", stop)
            spec = importlib.util.spec_from_file_location("system_mitigator", SCRIPT)
            env.mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(env.mod)
        # Later calls see fakes only through the module's own names.
        env.mod.subprocess = types.SimpleNamespace(run=env._run, CompletedProcess=subprocess.CompletedProcess)
        env.mod.glob = types.SimpleNamespace(glob=env._glob)
        env.mod.time = types.SimpleNamespace(time=lambda: env.now, sleep=stop)
        return env

    yield _load
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            h.close()


# --- startup / main loop ------------------------------------------------------

def test_startup_records_initial_restart_count_and_runs_one_pass(load):
    env = load(initial_journal=["NRestarts=7\n"])
    assert env.mod.last_journal_restarts == 7
    # The pass after startup queries systemctl again; no reading is queued, so that
    # query fails, is swallowed, and the baseline stays at the startup value.
    assert env.mod.throttle_seconds_accumulator == 0
    assert (Path(env.mod.log_dir)).is_dir()


def test_startup_survives_systemctl_failure(load):
    env = load(initial_journal=[subprocess.CalledProcessError(1, "systemctl")])
    assert env.mod.last_journal_restarts is None


# --- get_pkg_temp -------------------------------------------------------------

def test_pkg_temp_reads_x86_pkg_temp_zone_in_degrees(load):
    env = load()
    env.zone(0, "acpitz", 99000)
    env.zone(1, "x86_pkg_temp", 45500)
    assert env.mod.get_pkg_temp() == 45.5


def test_pkg_temp_none_without_matching_zone(load):
    env = load()
    env.zone(0, "acpitz", 50000)
    assert env.mod.get_pkg_temp() is None


def test_pkg_temp_none_without_any_zone(load):
    assert load().mod.get_pkg_temp() is None


def test_pkg_temp_none_on_unparsable_reading(load):
    env = load()
    env.zone(0, "x86_pkg_temp", "not-a-number")
    assert env.mod.get_pkg_temp() is None


# --- check_cpu_throttling -----------------------------------------------------

def test_throttle_without_cpufreq_files_changes_nothing(load):
    env = load()
    env.mod.check_cpu_throttling()
    assert env.mod.throttle_seconds_accumulator == 0
    assert env.notify_calls() == []


def test_all_cores_at_min_add_ten_seconds_per_pass(load):
    env = load()
    env.cpu(0, 400_000)
    env.cpu(1, 400_000)
    env.mod.check_cpu_throttling()
    env.mod.check_cpu_throttling()
    assert env.mod.throttle_seconds_accumulator == 20


def test_core_within_five_percent_of_min_counts_as_at_min(load):
    env = load()
    env.cpu(0, 420_000)  # 400000 * 1.05 == 420000
    env.mod.check_cpu_throttling()
    assert env.mod.throttle_seconds_accumulator == 10


def test_core_above_five_percent_of_min_breaks_the_streak(load):
    env = load()
    env.cpu(0, 400_000)
    env.cpu(1, 420_001)
    env.mod.throttle_seconds_accumulator = 50
    env.mod.check_cpu_throttling()
    assert env.mod.throttle_seconds_accumulator == 0


def test_core_without_min_file_is_not_counted_at_min(load):
    env = load()
    env.cpu(0, 400_000)
    env.cpu(1, 400_000, with_min=False)
    env.mod.check_cpu_throttling()
    assert env.mod.throttle_seconds_accumulator == 0


def test_unreadable_frequency_is_logged_not_raised(load):
    env = load()
    env.cpu(0, "garbage")
    env.mod.throttle_seconds_accumulator = 30
    env.mod.check_cpu_throttling()  # must not raise
    assert env.mod.throttle_seconds_accumulator == 30
    assert env.notify_calls() == []


def _lock_cores(env, accumulated):
    env.cpu(0, 400_000)
    env.cpu(1, 400_000)
    env.mod.throttle_seconds_accumulator = accumulated


def test_no_alert_before_sixty_seconds(load):
    env = load()
    _lock_cores(env, 40)  # becomes 50
    env.zone(0, "x86_pkg_temp", 50000)
    env.mod.check_cpu_throttling()
    assert env.notify_calls() == []


def test_alert_at_sixty_seconds_when_cool(load):
    env = load()
    _lock_cores(env, 50)  # becomes 60
    env.zone(0, "x86_pkg_temp", 50000)
    env.mod.check_cpu_throttling()
    (call,) = env.notify_calls()
    assert call[call.index("-u") + 1] == "normal"
    assert "CPU Throttle Bounce" in call
    assert "60s" in call[-1] and "50.0" in call[-1]
    assert env.mod.last_throttle_notification_time == START


def test_no_alert_when_cpu_is_hot(load):
    env = load()
    _lock_cores(env, 50)
    env.zone(0, "x86_pkg_temp", 65000)  # >= 65 C is real thermal throttling
    env.mod.check_cpu_throttling()
    assert env.notify_calls() == []


def test_no_alert_when_temperature_unknown(load):
    env = load()
    _lock_cores(env, 50)
    env.mod.check_cpu_throttling()
    assert env.notify_calls() == []


def test_throttle_alert_rate_limited_to_fifteen_minutes(load):
    env = load()
    _lock_cores(env, 50)
    env.zone(0, "x86_pkg_temp", 50000)
    env.mod.check_cpu_throttling()
    env.now += 900  # exactly 900s is still inside the window (strict >)
    env.mod.check_cpu_throttling()
    assert len(env.notify_calls()) == 1
    env.now += 1
    env.mod.check_cpu_throttling()
    assert len(env.notify_calls()) == 2


def test_recovery_resets_accumulator(load):
    env = load()
    env.cpu(0, 800_000)
    env.mod.throttle_seconds_accumulator = 20
    env.mod.check_cpu_throttling()
    assert env.mod.throttle_seconds_accumulator == 0


# --- get_journald_restarts ----------------------------------------------------

def test_journald_restarts_parsed_from_systemctl_show(load):
    env = load()
    env.journal = ["NRestarts=12\n"]
    assert env.mod.get_journald_restarts() == 12
    assert env.calls[-1] == ["systemctl", "show", "systemd-journald.service", "-p", "NRestarts"]


def test_journald_restarts_none_when_systemctl_fails(load):
    env = load()
    env.journal = [subprocess.CalledProcessError(1, "systemctl")]
    assert env.mod.get_journald_restarts() is None


def test_journald_restarts_none_when_property_absent(load):
    env = load()
    env.journal = ["\n"]
    assert env.mod.get_journald_restarts() is None


def test_journald_restarts_none_when_value_not_numeric(load):
    env = load()
    env.journal = ["NRestarts=many\n"]
    assert env.mod.get_journald_restarts() is None


# --- check_journald_health ----------------------------------------------------

def _health(env, reading):
    env.journal = [reading]
    env.mod.check_journald_health()


def test_first_reading_is_only_a_baseline(load):
    env = load(initial_journal=[subprocess.CalledProcessError(1, "systemctl")])
    assert env.mod.last_journal_restarts is None
    _health(env, "NRestarts=50\n")
    assert env.mod.last_journal_restarts == 50
    assert env.notify_calls() == []


def test_single_restart_logs_but_does_not_notify(load):
    env = load(initial_journal=["NRestarts=3\n"])
    _health(env, "NRestarts=4\n")
    assert env.mod.last_journal_restarts == 4
    assert env.notify_calls() == []


def test_unchanged_count_is_quiet(load):
    env = load(initial_journal=["NRestarts=3\n"])
    _health(env, "NRestarts=3\n")
    assert env.notify_calls() == []


def test_two_restarts_in_one_poll_send_critical_notification(load):
    env = load(initial_journal=["NRestarts=3\n"])
    _health(env, "NRestarts=5\n")
    (call,) = env.notify_calls()
    assert call[call.index("-u") + 1] == "critical"
    assert "System Service Crash Loop" in call
    assert "journalctl --vacuum-time=1s" in call[-1]
    assert env.mod.last_journal_notification_time == START


def test_crash_loop_notification_rate_limited_to_five_minutes(load):
    env = load(initial_journal=["NRestarts=0\n"])
    _health(env, "NRestarts=2\n")
    env.now += 300  # exactly 300s is still inside the window (strict >)
    _health(env, "NRestarts=4\n")
    assert len(env.notify_calls()) == 1
    env.now += 1
    _health(env, "NRestarts=6\n")
    assert len(env.notify_calls()) == 2


def test_failed_query_keeps_previous_baseline(load):
    env = load(initial_journal=["NRestarts=3\n"])
    _health(env, subprocess.CalledProcessError(1, "systemctl"))
    assert env.mod.last_journal_restarts == 3
    _health(env, "NRestarts=5\n")  # diff measured against 3, not lost
    assert len(env.notify_calls()) == 1


def test_counter_reset_below_baseline_does_not_notify(load):
    env = load(initial_journal=["NRestarts=9\n"])
    _health(env, "NRestarts=0\n")  # service unit reloaded: counter restarts at 0
    assert env.notify_calls() == []
    assert env.mod.last_journal_restarts == 0


# --- send_notification --------------------------------------------------------

def test_send_notification_normal_urgency_argv(load):
    env = load()
    env.mod.send_notification("T", "M")
    assert env.calls[-1] == [
        "notify-send", "-u", "normal", "-i", "dialog-information", "-a", "System Mitigator", "T", "M",
    ]


def test_send_notification_critical_urgency_argv(load):
    env = load()
    env.mod.send_notification("T", "M", critical=True)
    assert env.calls[-1][:6] == ["notify-send", "-u", "critical", "-i", "dialog-warning", "-a"]


def test_send_notification_swallows_notify_send_failure(load):
    env = load()

    def boom(argv, **kwargs):
        raise FileNotFoundError("notify-send")

    env.mod.subprocess = types.SimpleNamespace(run=boom)
    env.mod.send_notification("T", "M")  # must not raise
