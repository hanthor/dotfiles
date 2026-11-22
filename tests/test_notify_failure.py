import subprocess

from conftest import REPO, write_stub

NOTIFY = REPO / "roles/systemd/files/notify-failure.sh"
DISK = REPO / "roles/systemd/files/disk-usage-check.py"


def run_notify(env, *args):
    return subprocess.run(["bash", str(NOTIFY), *args], env=env,
                          capture_output=True, text=True, timeout=30)


def stubs(bindir, curl_rc=0):
    write_stub(bindir, "systemctl", "echo exit-code\n")
    write_stub(bindir, "hostname", "echo testhost\n")
    write_stub(bindir, "curl", f'printf "%s\\n" "$@" > "$CURL_LOG"\nexit {curl_rc}\n')


def test_no_topic_logs_and_exits_zero(stub_env, tmp_path):
    bindir, env = stub_env
    stubs(bindir)
    env.pop("NTFY_TOPIC", None)
    env["CURL_LOG"] = str(tmp_path / "curl.log")
    r = run_notify(env, "dotfiles-update.service")
    assert r.returncode == 0
    assert "testhost: dotfiles-update.service failed (result: exit-code)" in r.stderr
    assert "NTFY_TOPIC not set" in r.stderr
    assert not (tmp_path / "curl.log").exists()


def test_topic_posts_to_server(stub_env, tmp_path):
    bindir, env = stub_env
    stubs(bindir)
    log = tmp_path / "curl.log"
    env.update(NTFY_TOPIC="t0pic", NTFY_SERVER="https://ntfy.example/",
               CURL_LOG=str(log))
    r = run_notify(env, "disk-usage-check.service")
    assert r.returncode == 0
    args = log.read_text().splitlines()
    assert args[-1] == "https://ntfy.example/t0pic"
    assert "Title: testhost: disk-usage-check.service failed" in args


def test_post_failure_still_exits_zero(stub_env, tmp_path):
    bindir, env = stub_env
    stubs(bindir, curl_rc=22)
    env.update(NTFY_TOPIC="t", CURL_LOG=str(tmp_path / "curl.log"))
    r = run_notify(env, "x.service")
    assert r.returncode == 0
    assert "posting to ntfy failed" in r.stderr


def run_disk(*args):
    return subprocess.run(["python3", str(DISK), *args],
                          capture_output=True, text=True, timeout=30)


def test_disk_below_threshold_passes(tmp_path):
    r = run_disk("100", str(tmp_path))
    assert r.returncode == 0
    assert f"{tmp_path}:" in r.stdout


def test_disk_above_threshold_fails(tmp_path):
    # Any writable filesystem with data on it is above -1%.
    r = run_disk("-1", str(tmp_path))
    assert r.returncode == 1
    assert "over -1%" in r.stderr


def test_disk_skips_missing_and_duplicate_paths(tmp_path):
    (tmp_path / "a").mkdir()
    r = run_disk("100", str(tmp_path), str(tmp_path / "a"), str(tmp_path / "nope"))
    assert r.returncode == 0
    assert r.stdout.count("% used") == 1


def test_disk_usage_formula_matches_df():
    import importlib.util
    spec = importlib.util.spec_from_file_location("duc", DISK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class St:
        f_blocks, f_bfree, f_bavail = 100, 10, 5   # used 90 / (90+5)
    assert mod.usage_percent(St) == 95


def test_disk_usage_requires_args():
    assert run_disk("90").returncode == 2
