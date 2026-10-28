import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import REPO, write_stub

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")

ITEM = '{"login":{"username":"U","password":"P"},"fields":[{"name":"key","value":"K"}]}'


def stubs(bindir, status_out, status_rc=1, unlock_rc=0, version="18.24.0"):
    write_stub(
        bindir,
        "atuin",
        f"""echo "atuin $*" >> "$HOME/calls"
case "$1" in
  status) echo '{status_out}'; exit {status_rc} ;;
  --version) echo 'atuin {version}'; exit 0 ;;
  info) echo "key path: $HOME/.local/share/atuin/key"; exit "${{STUB_INFO_RC:-0}}" ;;
  key) cat "$HOME/.local/share/atuin/key"; exit $? ;;
  login) [ "$*" = 'login -u U' ] && [ "$ATUIN_PASSWORD" = P ] && [ "$ATUIN_ENCRYPTION_KEY" = K ] && [ "${{STUB_LOGIN_RC:-0}}" = 0 ]; exit $? ;;
esac
exit 0
""",
    )
    write_stub(
        bindir,
        "bw",
        f"""echo "bw $*" >> "$HOME/calls"
[ "$1 $2" = "unlock --check" ] && exit {unlock_rc}
[ "$1 $2 $3" = "get item atuin.sh" ] && {{ echo '{ITEM}'; exit "${{STUB_ITEM_RC:-0}}"; }}
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
    assert "atuin login -u U\n" in calls
    assert " -p " not in calls and " -k " not in calls


def test_missing_key_login_keeps_imported_history_and_permissions(stub_env):
    bindir, env = stub_env
    data = Path(env["HOME"], ".local/share/atuin")
    data.mkdir(parents=True, mode=0o755)
    data.chmod(0o755)
    (data / "history.db").write_bytes(b"existing history")
    (data / "history.db-wal").write_bytes(b"pending history")
    (data / ".history_imported").write_text("already imported")
    stubs(bindir, "not logged in")

    r, calls = run(env)

    assert r.returncode == 0, r.stdout + r.stderr
    assert "atuin login -u U\n" in calls
    assert "atuin import" not in calls
    assert (data / "history.db").read_bytes() == b"existing history"
    assert (data / "history.db-wal").read_bytes() == b"pending history"
    assert (data / ".history_imported").read_text() == "already imported"
    assert data.stat().st_mode & 0o777 == 0o700


def test_existing_different_key_is_never_replaced(stub_env):
    bindir, env = stub_env
    data = Path(env["HOME"], ".local/share/atuin")
    data.mkdir(parents=True)
    (data / "key").write_text("different key")
    (data / "history.db").write_bytes(b"existing history")
    stubs(bindir, "not logged in")

    r, calls = run(env)

    assert r.returncode == 0
    assert "existing Atuin key differs" in r.stdout
    assert "atuin login" not in calls and "atuin import" not in calls
    assert (data / "key").read_text() == "different key"
    assert (data / "history.db").read_bytes() == b"existing history"
    assert not (data / ".history_imported").exists()


def test_existing_matching_key_can_log_in(stub_env):
    bindir, env = stub_env
    data = Path(env["HOME"], ".local/share/atuin")
    data.mkdir(parents=True)
    (data / "key").write_text("K")
    stubs(bindir, "not logged in")

    r, calls = run(env)

    assert r.returncode == 0, r.stdout + r.stderr
    assert "atuin login -u U\n" in calls
    assert (data / "key").read_text() == "K"


def test_old_version_requests_manual_login(stub_env):
    bindir, env = stub_env
    stubs(bindir, "not logged in", version="18.23.0")

    r, calls = run(env)

    assert r.returncode == 0
    assert "run atuin login interactively" in r.stdout
    assert "atuin login" not in calls and "atuin import" not in calls


def test_no_secrets_keeps_history_without_touching_vault(stub_env):
    bindir, env = stub_env
    data = Path(env["HOME"], ".local/share/atuin")
    data.mkdir(parents=True)
    (data / "history.db").write_bytes(b"existing history")
    (data / ".history_imported").touch()
    stubs(bindir, "not logged in")

    r, calls = run({**env, "UNITS_NO_SECRETS": "1"})

    assert r.returncode == 0
    assert "PARTIAL:" in r.stdout
    assert "bw " not in calls and "atuin login" not in calls
    assert (data / "history.db").read_bytes() == b"existing history"


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


def test_failed_info_does_not_use_partial_key_path_or_import(stub_env):
    bindir, env = stub_env
    stubs(bindir, "not logged in")
    result, calls = run({**env, "STUB_INFO_RC": "1"})
    assert result.returncode == 0 and "cannot determine the Atuin key path" in result.stdout
    assert "atuin login" not in calls and "atuin import" not in calls


def test_failed_login_does_not_import_history(stub_env):
    bindir, env = stub_env
    stubs(bindir, "not logged in")
    result, calls = run({**env, "STUB_LOGIN_RC": "1"})
    assert result.returncode != 0 and "FAIL  atuin login" in result.stdout
    assert "atuin login" in calls and "atuin import" not in calls
    assert not Path(env["HOME"], ".local/share/atuin/.history_imported").exists()


def test_failed_vault_read_does_not_use_partial_credentials(stub_env):
    bindir, env = stub_env
    stubs(bindir, "not logged in")
    result, calls = run({**env, "STUB_ITEM_RC": "1"})
    assert result.returncode == 0 and "missing or incomplete" in result.stdout
    assert "atuin login" not in calls
