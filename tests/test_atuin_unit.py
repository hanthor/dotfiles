import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")

ITEM = '{"login":{"username":"U","password":"P"},"fields":[{"name":"key","value":"K"}]}'


def stubs(bindir, status_out, status_rc=1, unlock_rc=0):
    write_stub(
        bindir,
        "atuin",
        f"""echo "atuin $*" >> "$HOME/calls"
case "$1" in
  status) echo '{status_out}'; exit {status_rc} ;;
esac
exit 0
""",
    )
    write_stub(
        bindir,
        "bw",
        f"""echo "bw $*" >> "$HOME/calls"
[ "$1 $2" = "unlock --check" ] && exit {unlock_rc}
[ "$1 $2 $3" = "get item atuin.sh" ] && echo '{ITEM}'
exit 0
""",
    )


def run(env):
    env = {**env, "BW_SESSION": "x", "DOTFILES_DIR": str(REPO), "BREW_PREFIX": "/nonexistent"}
    r = subprocess.run(["bash", str(REPO / "units/atuin.sh")], env=env, capture_output=True, text=True)
    calls = Path(env["HOME"], "calls")
    return r, calls.read_text() if calls.exists() else ""


def test_logs_in_with_bitwarden_credentials(stub_env):
    bindir, env = stub_env
    stubs(bindir, "not logged in")
    r, calls = run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "atuin login -u U -p P -k K" in calls


def test_already_logged_in_never_touches_bitwarden(stub_env):
    bindir, env = stub_env
    stubs(bindir, "[Sync] ok", status_rc=0)
    r, calls = run(env)
    assert r.returncode == 0
    assert "login" not in calls and "bw " not in calls


def test_locked_vault_is_partial_and_does_not_login(stub_env):
    bindir, env = stub_env
    stubs(bindir, "not logged in", unlock_rc=1)
    r, calls = run(env)
    assert r.returncode == 0
    assert "PARTIAL:" in r.stdout
    assert "login" not in calls


def test_missing_atuin_is_skipped(stub_env):
    bindir, env = stub_env
    env["PATH"] = f"{bindir}:/usr/bin:/bin"
    r, _ = run(env)
    assert r.returncode == 0
    assert "SKIPPED:" in r.stdout
