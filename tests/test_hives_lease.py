"""hives/hive-failover, hive-reconcile, hive-notify and hive-drift-check
decision logic against PATH-injected fake ssh/podman/curl/docker/logger.

Nothing here touches a network or a real host: state dirs are tmp dirs passed
through the scripts' env seams (HIVE_FAILOVER_STATE, HIVE_HOST_DIR, ...).
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

from conftest import REPO, write_stub

HIVES = REPO / "hives"

# Logs every call as one line "name arg1 arg2 ..." to $FAKE_LOG.
LOG = 'echo "$(basename "$0") $*" >> "$FAKE_LOG"\n'

CURL = LOG + r'''
url=${@: -1}
case "$url" in
  https://ntfy.sh/*) exit 0 ;;
  http://*) port=${url##*:}; port=${port%/}
            for p in ${FAKE_DOWN_PORTS:-}; do [ "$p" = "$port" ] && exit 22; done
            exit 0 ;;
esac
exit 0
'''

# ssh for hive-failover (rsh james@ip CMD) and hive-reconcile (lease read).
SSH = LOG + r'''
cmd=${@: -1}
case "$cmd" in
  ubuntu@*) [ "${FAKE_LEASE-}" = UNREACHABLE ] && exit 255; echo "$FAKE_LEASE"; exit 0 ;;
  *"podman ps"*) for a in "$@"; do case "$a" in james@100.103.44.48) echo "${FAKE_RUNNING_bihar:-0}";;
                   james@100.66.158.127) echo "${FAKE_RUNNING_karnataka:-0}";; esac; done; exit 0 ;;
  *) exit 0 ;;
esac
'''


@pytest.fixture
def env(stub_env, tmp_path):
    bindir, e = stub_env
    log = tmp_path / "calls.log"
    log.touch()
    e["FAKE_LOG"] = str(log)
    write_stub(bindir, "curl", CURL)
    write_stub(bindir, "ssh", SSH)
    write_stub(bindir, "docker", LOG)
    write_stub(bindir, "logger", LOG)
    write_stub(bindir, "sleep", LOG)
    write_stub(bindir, "podman", LOG + 'echo "${FAKE_PODMAN_PS:-}" | tr " " "\\n" | grep .\n')
    write_stub(bindir, "hostname", 'echo "${FAKE_HOSTNAME:-bihar}"\n')
    envfile = tmp_path / "hive-failover.env"
    envfile.write_text("NTFY_TOPIC=test-topic\n")
    e["HIVE_NTFY_ENV"] = f"{envfile} {tmp_path}/missing.env"
    e.pop("NTFY_TOPIC", None)
    return e, log


def calls(log, prefix=None):
    lines = log.read_text().splitlines()
    return [l for l in lines if prefix is None or l.startswith(prefix)]


def ntfy(log):
    return [l for l in calls(log, "curl") if "https://ntfy.sh/" in l]


def run(script, e, *args):
    return subprocess.run(["bash", str(HIVES / script), *args], env=e,
                          capture_output=True, text=True, timeout=60)


def ago(minutes):
    return str(int(time.time()) - minutes * 60)


# ── hive-failover (spindle) ─────────────────────────────────────────────

@pytest.fixture
def fo(env, tmp_path):
    e, log = env
    state = tmp_path / "state"
    state.mkdir()
    (state / "active").write_text("bihar\n")
    caddy = tmp_path / "Caddyfile"
    caddy.write_text("".join(f"reverse_proxy 100.103.44.48:{p}\n" for p in range(3100, 3105)))
    e.update(HIVE_FAILOVER_STATE=str(state), HIVE_FAILOVER_CADDYFILE=str(caddy))
    return e, log, state, caddy


def lease(state):
    return (state / "active").read_text().strip()


def test_failover_all_healthy_no_change(fo):
    e, log, state, _ = fo
    r = run("hive-failover", e, "check")
    assert r.returncode == 0
    assert lease(state) == "bihar"
    assert not calls(log, "ssh") and not ntfy(log)
    assert not (state / "down_since").exists()


def test_failover_core_port_down_short_waits(fo):
    e, log, state, _ = fo
    e["FAKE_DOWN_PORTS"] = "3102"
    run("hive-failover", e, "check")
    assert lease(state) == "bihar"
    assert (state / "down_since").exists()
    assert not calls(log, "ssh")


def test_failover_core_port_down_past_fail_min_revokes(fo):
    """Existing behaviour: hub/school/reef down >= FAIL_MIN moves the hives."""
    e, log, state, _ = fo
    e.update(FAKE_DOWN_PORTS="3102", FAKE_RUNNING_bihar="5")
    (state / "down_since").write_text(ago(6))
    run("hive-failover", e, "check")
    assert lease(state) == "none"
    assert (state / "pending").read_text().strip() == "karnataka"
    assert any("100.103.44.48" in l and "hives stop" in l for l in calls(log, "ssh"))
    assert ntfy(log), "failover must notify"


def test_failover_pending_old_stopped_activates(fo):
    e, log, state, caddy = fo
    (state / "active").write_text("none\n")
    (state / "pending").write_text("karnataka\n")
    (state / "down_since").write_text(ago(6))
    e["FAKE_RUNNING_bihar"] = "0"
    run("hive-failover", e, "check")
    assert lease(state) == "karnataka"
    assert "100.66.158.127:3104" in caddy.read_text()
    assert "100.103.44.48" not in caddy.read_text()
    assert not (state / "pending").exists()


def test_failover_pending_old_still_running_waits(fo):
    e, log, state, _ = fo
    (state / "active").write_text("none\n")
    (state / "pending").write_text("karnataka\n")
    (state / "down_since").write_text(ago(6))
    e["FAKE_RUNNING_bihar"] = "3"
    run("hive-failover", e, "check")
    assert lease(state) == "none"
    assert (state / "pending").exists()


@pytest.mark.parametrize("port", ["3100", "3104"])
def test_failover_alert_port_down_never_moves(fo, port):
    """hub-front / hanthor down far past FAIL_MIN: alert once, no move."""
    e, log, state, caddy = fo
    before = caddy.read_text()
    e["FAKE_DOWN_PORTS"] = port
    (state / "degraded").write_text(ago(30))
    for _ in range(2):
        r = run("hive-failover", e, "check")
        assert r.returncode == 0
    assert lease(state) == "bihar"
    assert not (state / "down_since").exists()
    assert not (state / "pending").exists()
    assert not calls(log, "ssh"), "alert ports must not stop the hives"
    assert caddy.read_text() == before
    assert len(ntfy(log)) == 1
    assert port in ntfy(log)[0]


def test_failover_alert_port_short_no_alert_then_recovery(fo):
    e, log, state, _ = fo
    e["FAKE_DOWN_PORTS"] = "3104"
    run("hive-failover", e, "check")
    assert (state / "degraded").exists() and not ntfy(log)
    (state / "degraded").write_text(ago(6))
    run("hive-failover", e, "check")
    assert len(ntfy(log)) == 1
    e["FAKE_DOWN_PORTS"] = ""
    run("hive-failover", e, "check")
    assert len(ntfy(log)) == 2 and "answer again" in ntfy(log)[1]
    assert not (state / "degraded").exists()


def test_failover_hold_does_nothing(fo):
    e, log, state, _ = fo
    (state / "hold").touch()
    e["FAKE_DOWN_PORTS"] = "3101 3102 3103"
    (state / "down_since").write_text(ago(60))
    run("hive-failover", e, "check")
    assert lease(state) == "bihar" and not calls(log, "curl")


def test_failover_topic_env_file_order(fo, tmp_path):
    e, log, state, _ = fo
    legacy = tmp_path / "legacy.env"
    legacy.write_text("NTFY_TOPIC=legacy\n")
    e["HIVE_NTFY_ENV"] = f"{tmp_path}/nope.env {legacy}"
    e.update(FAKE_DOWN_PORTS="3104")
    (state / "degraded").write_text(ago(10))
    run("hive-failover", e, "check")
    assert ntfy(log) and ntfy(log)[0].endswith("https://ntfy.sh/legacy")


# ── hive-reconcile (bihar / karnataka) ──────────────────────────────────

@pytest.fixture
def rc(env, tmp_path):
    e, log = env
    h = tmp_path / "hives-host"
    (h / "keys").mkdir(parents=True)
    rundir = tmp_path / "run"
    rundir.mkdir()
    # Fake compose wrapper: `config --services` lists $FAKE_SERVICES.
    (h / "hives").write_text(
        LOG.replace("$(basename \"$0\")", "hives") +
        'if [ "$1" = config ]; then [ -n "${FAKE_SERVICES_FAIL:-}" ] && exit 1\n'
        '  for s in ${FAKE_SERVICES-hub hub-front school reef hanthor}; do echo $s; done; fi\n')
    for f in ("hive-notify",):
        (h / f).write_text((HIVES / f).read_text())
    (h / "last-sync-to-karnataka").write_text("2026-01-01T00:00:00Z\n")
    e.update(HIVE_HOST_DIR=str(h), HIVE_RUN_DIR=str(rundir), FAKE_HOSTNAME="bihar")
    return e, log, h, rundir


def ps(n):
    return " ".join(f"c{i}" for i in range(n))


def hives_cmds(log):
    return [l for l in calls(log, "hives") if "config" not in l]


@pytest.mark.parametrize("running,started", [(0, True), (3, True), (4, True), (5, False)])
def test_reconcile_starts_until_all_compose_services_run(rc, running, started):
    """Item 10: 4 of 5 running used to count as healthy."""
    e, log, h, _ = rc
    e.update(FAKE_LEASE="bihar", FAKE_PODMAN_PS=ps(running))
    run("hive-reconcile", e)
    assert (hives_cmds(log) == ["hives up -d"]) is started


def test_reconcile_compose_failure_falls_back_to_five(rc):
    e, log, h, _ = rc
    e.update(FAKE_LEASE="bihar", FAKE_PODMAN_PS=ps(4), FAKE_SERVICES_FAIL="1")
    run("hive-reconcile", e)
    assert hives_cmds(log) == ["hives up -d"]
    e["FAKE_PODMAN_PS"] = ps(5)
    log.write_text("")
    run("hive-reconcile", e)
    assert hives_cmds(log) == []


def test_reconcile_maintenance_skips_start(rc):
    e, log, h, _ = rc
    (h / "maintenance").touch()
    e.update(FAKE_LEASE="bihar", FAKE_PODMAN_PS="")
    run("hive-reconcile", e)
    assert hives_cmds(log) == []


@pytest.mark.parametrize("other", ["karnataka", "none"])
def test_reconcile_lease_elsewhere_stops(rc, other):
    e, log, h, _ = rc
    e.update(FAKE_LEASE=other, FAKE_PODMAN_PS=ps(5))
    run("hive-reconcile", e)
    assert hives_cmds(log) == ["hives stop"]
    assert not ntfy(log)


def test_reconcile_unreadable_short_keeps_running(rc):
    e, log, h, rundir = rc
    (rundir / "hive-reconcile.last-ok").write_text(ago(3))
    e.update(FAKE_LEASE="UNREACHABLE", FAKE_PODMAN_PS=ps(5))
    run("hive-reconcile", e)
    assert hives_cmds(log) == [] and not ntfy(log)


def test_reconcile_self_fence_stops_and_alerts_once(rc):
    """Item 11: fencing unchanged, plus one alert."""
    e, log, h, rundir = rc
    (rundir / "hive-reconcile.last-ok").write_text(ago(9))
    e.update(FAKE_LEASE="UNREACHABLE", FAKE_PODMAN_PS=ps(5))
    run("hive-reconcile", e)
    assert hives_cmds(log) == ["hives stop"]
    assert len(ntfy(log)) == 1 and "self-fenced" in calls(log, "curl")[0]
    run("hive-reconcile", e)   # stop failed / still running: no second alert
    assert len(ntfy(log)) == 1
    e["FAKE_LEASE"] = "bihar"  # spindle back: re-arms the alert
    run("hive-reconcile", e)
    assert not (rundir / "hive-reconcile.fenced").exists()


def test_reconcile_fence_without_notify_helper_still_stops(rc):
    e, log, h, rundir = rc
    (h / "hive-notify").unlink()
    (rundir / "hive-reconcile.last-ok").write_text(ago(9))
    e.update(FAKE_LEASE="UNREACHABLE", FAKE_PODMAN_PS=ps(5))
    r = run("hive-reconcile", e)
    assert hives_cmds(log) == ["hives stop"] and not ntfy(log)
    assert r.returncode == 0


def set_mtime(p, minutes):
    t = time.time() - minutes * 60
    os.utime(p, (t, t))


def test_reconcile_stale_sync_alerts_once(rc):
    """Item 17: last-sync-to-<peer> older than 1h while holding the lease."""
    e, log, h, rundir = rc
    set_mtime(h / "last-sync-to-karnataka", 120)
    (rundir / "hive-reconcile.own-since").write_text(ago(180))
    e.update(FAKE_LEASE="bihar", FAKE_PODMAN_PS=ps(5))
    run("hive-reconcile", e)
    run("hive-reconcile", e)
    assert len(ntfy(log)) == 1
    assert "karnataka" in calls(log, "curl")[0]
    os.utime(h / "last-sync-to-karnataka")   # a sync ran
    run("hive-reconcile", e)
    assert len(ntfy(log)) == 2 and "current again" in ntfy(log)[1]


def test_reconcile_stale_sync_grace_after_taking_lease(rc):
    e, log, h, rundir = rc
    set_mtime(h / "last-sync-to-karnataka", 600)
    e.update(FAKE_LEASE="bihar", FAKE_PODMAN_PS=ps(5))
    run("hive-reconcile", e)   # own-since starts now
    assert not ntfy(log)
    assert (rundir / "hive-reconcile.own-since").exists()


def test_reconcile_fresh_sync_no_alert_and_standby_never_checks(rc):
    e, log, h, rundir = rc
    (rundir / "hive-reconcile.own-since").write_text(ago(180))
    e.update(FAKE_LEASE="bihar", FAKE_PODMAN_PS=ps(5))
    run("hive-reconcile", e)
    assert not ntfy(log)
    set_mtime(h / "last-sync-to-karnataka", 600)
    e.update(FAKE_LEASE="karnataka", FAKE_PODMAN_PS="")
    run("hive-reconcile", e)
    assert not ntfy(log)
    assert not (rundir / "hive-reconcile.own-since").exists()


# ── hive-notify ─────────────────────────────────────────────────────────

def test_notify_prefers_etc_env_then_legacy(env, tmp_path):
    e, log = env
    first = tmp_path / "etc.env"
    first.write_text('NTFY_TOPIC="primary"\n')
    legacy = tmp_path / "legacy.env"
    legacy.write_text("NTFY_TOPIC=legacy\n")
    e["HIVE_NTFY_ENV"] = f"{first} {legacy}"
    assert run("hive-notify", e, "t", "hello").returncode == 0
    assert ntfy(log)[-1].endswith("https://ntfy.sh/primary")
    first.write_text("OTHER=1\n")
    run("hive-notify", e, "t", "hello")
    assert ntfy(log)[-1].endswith("https://ntfy.sh/legacy")


def test_notify_without_topic_only_logs(env, tmp_path):
    e, log = env
    e["HIVE_NTFY_ENV"] = f"{tmp_path}/none.env"
    assert run("hive-notify", e, "t", "hello").returncode == 0
    assert not ntfy(log) and calls(log, "logger")


# ── hive-drift-check (read-only) ────────────────────────────────────────

def install_host_files(root, h):
    """Install every host-mapped file exactly as in the repo, under root."""
    sysd = root / "etc/systemd/system"
    sysd.mkdir(parents=True)
    hh = root / str(h).lstrip("/")
    hh.mkdir(parents=True, exist_ok=True)
    for f in ("hives", "hive-reconcile", "hive-sync", "hive-cleanup",
              "hive-roster-sync", "hive-notify", "hive-drift-check", "compose.bihar.yaml"):
        (hh / f).write_bytes((HIVES / f).read_bytes())
    (hh / "hanthor-roster.conf").write_bytes((HIVES / "hanthor/roster.conf").read_bytes())
    for u in ("hive-reconcile", "hive-sync", "hive-cleanup", "hive-roster-sync", "hive-drift-check"):
        for ext in ("service", "timer"):
            (sysd / f"{u}.{ext}").write_bytes((HIVES / f"systemd/{u}.{ext}").read_bytes())
    return hh, sysd


@pytest.fixture
def dc(env, tmp_path):
    e, log = env
    root = tmp_path / "root"
    h = "/var/srv/hives-host"
    hh, sysd = install_host_files(root, h)
    e.update(HIVE_DRIFT_ROOT=str(root), HIVE_DRIFT_REPO=str(REPO), HIVE_HOST_DIR=h,
             FAKE_HOSTNAME="bihar")
    return e, log, hh, sysd


def snapshot(d):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(d).rglob("*") if p.is_file()}


def test_drift_none(dc):
    e, log, hh, _ = dc
    r = run("hive-drift-check", e, "host")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no drift" in r.stdout and not ntfy(log)


def test_drift_detected_is_read_only(dc, tmp_path):
    e, log, hh, sysd = dc
    (hh / "hive-reconcile").write_text("#!/bin/bash\n# edited by hand\n")
    (sysd / "hive-sync.timer").unlink()
    before = snapshot(tmp_path / "root")
    r = run("hive-drift-check", e, "host")
    assert r.returncode == 1
    out = r.stdout
    assert "/var/srv/hives-host/hive-reconcile" in out
    assert "hive-sync.timer" in out and "Not installed" in out
    assert "edited by hand" not in out, "alerts carry file names, never contents"
    assert len(ntfy(log)) == 1
    assert snapshot(tmp_path / "root") == before, "drift check must not modify installed files"


def test_drift_fetch_failure_is_not_drift(dc, tmp_path):
    e, log, hh, _ = dc
    e["HIVE_DRIFT_REPO"] = str(tmp_path / "no-such-checkout")
    r = run("hive-drift-check", e, "host")
    assert r.returncode == 2
    assert "could not fetch" in r.stdout


def test_drift_unit_files_verify():
    if not shutil_which("systemd-analyze"):
        pytest.skip("no systemd-analyze")
    units = [str(HIVES / "systemd" / f"hive-drift-check.{x}") for x in ("service", "timer")]
    r = subprocess.run(["systemd-analyze", "verify", *units], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def shutil_which(name):
    import shutil
    return shutil.which(name)
