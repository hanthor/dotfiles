import json
import os
import subprocess
import sys
import time

from conftest import REPO


def run(env, *args):
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "record-apply.py"), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


def base_env(tmp_path):
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    return env


def read_recorded(tmp_path):
    path = tmp_path / ".cache" / "dotfiles" / "last-apply.json"
    return json.loads(path.read_text())


def test_no_args_prints_usage_and_exits_2(tmp_path):
    r = run(base_env(tmp_path))
    assert r.returncode == 2
    assert "usage: record-apply.py" in r.stderr


def test_records_exit_code_and_defaults(tmp_path):
    before = int(time.time())
    r = run(base_env(tmp_path), "0")
    after = int(time.time())
    assert r.returncode == 0

    data = read_recorded(tmp_path)
    assert data["exit_code"] == 0
    assert data["label"] == "apply"
    assert data["skip_tags"] == ""
    assert before <= data["epoch"] <= after
    assert data["hostname"] == os.uname().nodename


def test_records_custom_label_and_skip_tags(tmp_path):
    r = run(base_env(tmp_path), "1", "bootstrap", "slow,network")
    assert r.returncode == 0

    data = read_recorded(tmp_path)
    assert data["exit_code"] == 1
    assert data["label"] == "bootstrap"
    assert data["skip_tags"] == "slow,network"


def test_missing_git_repo_falls_back_to_unknown_branch_and_commit(tmp_path):
    # HOME is isolated, so ~/.local/share/dotfiles does not exist; the git()
    # helper must swallow the failure and fall back to "?" rather than crash.
    r = run(base_env(tmp_path), "0")
    assert r.returncode == 0

    data = read_recorded(tmp_path)
    assert data["branch"] == "?"
    assert data["commit"] == "?"


def test_timestamp_is_iso8601_utc(tmp_path):
    r = run(base_env(tmp_path), "0")
    assert r.returncode == 0

    data = read_recorded(tmp_path)
    # Format: %Y-%m-%dT%H:%M:%SZ
    parsed = time.strptime(data["timestamp"], "%Y-%m-%dT%H:%M:%SZ")
    assert parsed.tm_year >= 2024


def test_creates_cache_dir_if_missing(tmp_path):
    cache_dir = tmp_path / ".cache" / "dotfiles"
    assert not cache_dir.exists()
    r = run(base_env(tmp_path), "0")
    assert r.returncode == 0
    assert cache_dir.is_dir()


def test_overwrites_previous_record(tmp_path):
    run(base_env(tmp_path), "1", "first")
    run(base_env(tmp_path), "0", "second")

    data = read_recorded(tmp_path)
    assert data["exit_code"] == 0
    assert data["label"] == "second"
