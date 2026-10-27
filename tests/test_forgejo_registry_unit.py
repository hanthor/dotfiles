import pytest

from conftest import write_stub
from unit_helpers import UNLOCKED_BW, calls, run_unit

CREDS = """\
if [ "$1" = get ]; then
  case "$2" in
    username) echo " ci-user "; exit 0 ;;
    password) [ -n "$STUB_NO_PASS" ] && exit 1; echo "tok123"; exit 0 ;;
  esac
fi
"""


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "bw", UNLOCKED_BW % CREDS)
    write_stub(bindir, "podman", 'echo "podman $*" >> "$HOME/calls"\ncase "$1 $2" in "login --get-login") exit "${STUB_LOGGED_IN:-1}" ;; esac\ncat >> "$HOME/stdin" 2>/dev/null\nexit 0\n')
    env["BW_SESSION"] = "x"
    return env


def test_logs_in_with_the_bitwarden_credential_on_stdin(env):
    from pathlib import Path

    r = run_unit("forgejo-registry", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "podman login forgejo.manatee-basking.ts.net -u ci-user --password-stdin" in calls(env)
    assert Path(env["HOME"], "stdin").read_text() == "tok123"
    assert "tok123" not in calls(env) + r.stdout + r.stderr


def test_already_logged_in_never_touches_bitwarden(env):
    r = run_unit("forgejo-registry", env, STUB_LOGGED_IN="0")
    assert r.returncode == 0 and "bw " not in calls(env) and "--password-stdin" not in calls(env)


def test_missing_credential_is_partial_not_a_failure(env):
    r = run_unit("forgejo-registry", env, STUB_NO_PASS="1")
    assert r.returncode == 0 and "PARTIAL:" in r.stdout
    assert "--password-stdin" not in calls(env)


def test_locked_vault_is_skipped(env):
    r = run_unit("forgejo-registry", env, STUB_UNLOCK_RC="1")
    assert r.returncode == 0 and "SKIPPED:" in r.stdout
