import json
import subprocess

import pytest

from conftest import REPO, write_stub

SCRIPT = REPO / "roles/hive_ops/files/bin/hive-peak.sh"

# Fake kubectl: one pod, one unexpired owner session, and a dashboard whose
# POSTs succeed except for agents listed in $STUB_FAIL. POSTs go to $STUB_LOG.
KUBECTL_STUB = r'''
[ "$1" = get ] && { echo hive-0; exit 0; }
shift 5   # exec -n hive hive-0 --
case "$1" in
  cat) echo '{"sid-1":{"Role":"owner","ExpiresAt":"2099-01-01T00:00:00Z"}}' ;;
  curl)
    method=$4 url=${!#}
    [ "$method" = GET ] && { cat "$STUB_STATUS"; exit 0; }
    agent=${url##*/}
    echo "$method ${url#http://127.0.0.1:3002}" >> "$STUB_LOG"
    case " ${STUB_FAIL:-} " in
      *" $agent "*) echo '{"ok":false,"error":"boom"}' ;;
      *) echo '{"ok":true,"status":"done"}' ;;
    esac ;;
esac
'''

AGENTS = [
    {"name": "ds1", "govModel": "deepseek-chat", "paused": False},
    {"name": "ds2", "cli": "pi", "paused": False},
    {"name": "ds3", "govModel": "deepseek-reasoner", "paused": False},
    {"name": "claude1", "govModel": "claude-opus", "paused": False},
    {"name": "login", "govModel": "deepseek-chat", "paused": True},
]


@pytest.fixture
def hive(stub_env, tmp_path):
    bindir, env = stub_env
    write_stub(bindir, "kubectl", KUBECTL_STUB)
    (tmp_path / "status.json").write_text(json.dumps({"agents": AGENTS}))
    state = tmp_path / "state"
    log = tmp_path / "posts.log"
    log.touch()
    env.update(STUB_STATUS=str(tmp_path / "status.json"), STUB_LOG=str(log),
               HIVE_PEAK_STATE=str(state))
    env.pop("HIVE_PEAK_PROVIDERS", None)

    def run(action, fail=""):
        env["STUB_FAIL"] = fail
        return subprocess.run(["bash", str(SCRIPT), action], env=env,
                              capture_output=True, text=True, timeout=30)
    return run, state, log


def lines(p):
    return p.read_text().split()


def test_pause_only_unpaused_deepseek(hive):
    run, state, log = hive
    r = run("pause")
    assert r.returncode == 0, r.stdout + r.stderr
    assert lines(state) == ["ds1", "ds2", "ds3"]
    assert "claude1" not in log.read_text() and "login" not in log.read_text()


def test_second_pause_merges(hive):
    run, state, _ = hive
    state.write_text("earlier\n")
    r = run("pause", fail="ds2")
    assert r.returncode == 1
    assert lines(state) == ["ds1", "ds3", "earlier"]


def test_partial_resume_keeps_failures(hive):
    run, state, log = hive
    state.write_text("ds1\nds2\nds3\n")
    r = run("resume", fail="ds2 ds3")
    assert r.returncode == 1
    assert lines(state) == ["ds2", "ds3"]
    assert lines(log) == ["POST", "/api/resume/ds1", "POST", "/api/resume/ds2",
                          "POST", "/api/resume/ds3"]


def test_full_resume_deletes_state(hive):
    run, state, _ = hive
    state.write_text("ds1\nds2\n")
    r = run("resume")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not state.exists()


def test_resume_without_state_touches_nothing(hive):
    run, _, log = hive
    r = run("resume")
    assert r.returncode == 0 and "nothing to resume" in r.stdout
    assert log.read_text() == ""
