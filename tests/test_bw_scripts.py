import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub

# Fake bw: `unlock --check` passes only for $STUB_VALID; `status` reports
# $STUB_STATUS; `unlock --raw` prints $STUB_NEW (or fails if unset). Every call
# is logged to $STUB_LOG.
BW_STUB = r'''
echo "$* BW_SESSION=${BW_SESSION:-}" >> "$STUB_LOG"
case "$1 ${2:-}" in
  "unlock --check") [ "${BW_SESSION:-}" = "${STUB_VALID:-}" ] ;;
  "status ") printf '{"status":"%s"}\n' "${STUB_STATUS:-locked}" ;;
  "unlock --raw") [ -n "${STUB_NEW:-}" ] && printf '%s' "$STUB_NEW" ;;
  *) exit 99 ;;
esac
'''


@pytest.fixture
def bw(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "bw", BW_STUB)
    env.update(STUB_LOG=str(tmp_path / "bw.log"), BW_SESSION_CACHE=str(tmp_path / "bw_session"))
    (tmp_path / "bw.log").touch()
    return env, tmp_path / "bw_session", tmp_path / "bw.log"


def run(script, env, *args):
    return subprocess.run(["bash", str(REPO / "scripts" / script), *args], env=env,
                          capture_output=True, text=True, timeout=30)


def test_unlock_env_wins(bw):
    env, cache, log = bw
    cache.write_text("cached")
    env.update(BW_SESSION="from-env", STUB_VALID="cached")
    r = run("bw-unlock.sh", env)
    assert (r.returncode, r.stdout) == (0, "from-env")
    assert log.read_text() == ""


def test_unlock_valid_cache(bw):
    env, cache, log = bw
    cache.write_text("cached")
    env.update(STUB_VALID="cached", STUB_NEW="fresh")
    r = run("bw-unlock.sh", env)
    assert (r.returncode, r.stdout) == (0, "cached")
    assert "unlock --raw" not in log.read_text()


def test_unlock_invalid_cache_falls_through(bw):
    env, cache, log = bw
    cache.write_text("stale")
    env.update(STUB_VALID="other", STUB_NEW="fresh")
    r = run("bw-unlock.sh", env)
    assert (r.returncode, r.stdout) == (0, "fresh")
    assert "unlock --check BW_SESSION=stale" in log.read_text()
    assert "unlock --raw" in log.read_text()
    assert cache.read_text() == "fresh"
    assert cache.stat().st_mode & 0o777 == 0o600


def test_unlock_invalid_cache_deleted_on_failure(bw):
    env, cache, _ = bw
    cache.write_text("stale")
    r = run("bw-unlock.sh", env)
    assert r.returncode == 4
    assert not cache.exists()


def test_unlock_unauthenticated(bw):
    env, cache, log = bw
    env.update(STUB_STATUS="unauthenticated", STUB_NEW="fresh")
    r = run("bw-unlock.sh", env)
    assert (r.returncode, r.stdout) == (3, "")
    assert "unlock --raw" not in log.read_text()
    assert not cache.exists()


@pytest.mark.parametrize("session", ["plain", "a b'c\"d$(touch pwned)`x`;e|f&g*", "x\ny"])
def test_resolve_local_round_trips(bw, session):
    env, _, _ = bw
    env.update(STUB_NEW=session)
    r = run("bw-resolve.sh", env, "local")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("export BW_SESSION=")
    check = subprocess.run(["bash", "-c", r.stdout + 'printf %s "$BW_SESSION"'],
                           cwd=env["HOME"], env=env, capture_output=True, text=True)
    assert check.stdout == session
    assert not (Path(env["HOME"]) / "pwned").exists()


def test_resolve_local_unlock_fails(bw):
    env, _, _ = bw
    r = run("bw-resolve.sh", env, "local")
    assert (r.returncode, r.stdout) == (1, "")
