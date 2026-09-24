import json
import subprocess
import sys
import time

from conftest import REPO


def run(env):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "last-apply-status.py")],
        env=env, capture_output=True, text=True, timeout=30,
    )


def write_status(home, data):
    cache_dir = home / ".cache" / "dotfiles"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "last-apply.json").write_text(json.dumps(data))


def base_env(tmp_path, extra=None):
    import os
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    if extra:
        env.update(extra)
    return env


def test_missing_file_reports_warning_and_exits_nonzero(tmp_path):
    r = run(base_env(tmp_path))
    assert r.returncode == 1
    assert "could not read" in r.stdout


def test_malformed_json_reports_warning_and_exits_nonzero(tmp_path):
    home = tmp_path
    cache_dir = home / ".cache" / "dotfiles"
    cache_dir.mkdir(parents=True)
    (cache_dir / "last-apply.json").write_text("{not valid json")
    r = run(base_env(tmp_path))
    assert r.returncode == 1
    assert "could not read" in r.stdout


def test_recent_success_exits_zero_and_shows_check_icon(tmp_path):
    now = int(time.time())
    write_status(tmp_path, {
        "epoch": now, "exit_code": 0, "label": "apply",
        "skip_tags": "", "branch": "master", "commit": "abc1234",
    })
    r = run(base_env(tmp_path))
    assert r.returncode == 0
    assert "✓" in r.stdout
    assert "abc1234" in r.stdout
    assert "master" in r.stdout
    assert "(rc=0, skipped=(none))" in r.stdout


def test_recent_failure_exits_nonzero_and_shows_warning_icon(tmp_path):
    now = int(time.time())
    write_status(tmp_path, {
        "epoch": now, "exit_code": 1, "label": "apply",
        "branch": "master", "commit": "abc1234",
    })
    r = run(base_env(tmp_path))
    assert r.returncode == 1
    assert "⚠" in r.stdout
    assert "(rc=1" in r.stdout


def test_stale_recent_success_still_exits_nonzero(tmp_path):
    stale_epoch = int(time.time()) - 49 * 3600
    write_status(tmp_path, {
        "epoch": stale_epoch, "exit_code": 0, "label": "apply",
        "branch": "master", "commit": "abc1234",
    })
    r = run(base_env(tmp_path))
    assert r.returncode == 1
    assert "stale" in r.stdout
    assert "⚠" in r.stdout


def test_fresh_success_just_under_threshold_is_not_stale(tmp_path):
    fresh_epoch = int(time.time()) - 47 * 3600
    write_status(tmp_path, {
        "epoch": fresh_epoch, "exit_code": 0, "label": "apply",
        "branch": "master", "commit": "abc1234",
    })
    r = run(base_env(tmp_path))
    assert r.returncode == 0
    assert "stale" not in r.stdout


def test_skip_tags_defaults_to_none_placeholder(tmp_path):
    now = int(time.time())
    write_status(tmp_path, {
        "epoch": now, "exit_code": 0, "label": "apply",
        "branch": "master", "commit": "abc1234",
    })
    r = run(base_env(tmp_path))
    assert "skipped=(none)" in r.stdout


def test_custom_skip_tags_are_shown(tmp_path):
    now = int(time.time())
    write_status(tmp_path, {
        "epoch": now, "exit_code": 0, "label": "apply",
        "skip_tags": "slow,network", "branch": "master", "commit": "abc1234",
    })
    r = run(base_env(tmp_path))
    assert "skipped=slow,network" in r.stdout


def test_missing_fields_fall_back_to_defaults(tmp_path):
    now = int(time.time())
    write_status(tmp_path, {"epoch": now})
    r = run(base_env(tmp_path))
    # rc defaults to -1 (missing "exit_code"), which is != 0, so exit is nonzero.
    assert r.returncode == 1
    assert "(rc=-1" in r.stdout
    assert " apply " in r.stdout
    assert "on ?" in r.stdout
