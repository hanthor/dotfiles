import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import write_stub
from unit_helpers import UNLOCKED_BW, calls, run_unit

PUB = "ssh-ed25519 AAAAKEYBODY james@host\n"

GH = """\
echo "gh $*" >> "$HOME/calls"
case "$1 $2" in
  "auth status")
    [ "$3" = "-t" ] && echo "  - Token scopes: $STUB_SCOPES"
    [ "$3" = "-t" ] || exit "${STUB_AUTHED:-0}"
    exit 0 ;;
  "auth login") cat > "$HOME/token"; exit 0 ;;
  "api --paginate")
    case "$*" in *user/ssh_signing_keys*) kind=signing ;; *) kind=authentication ;; esac
    printf '%s' "$STUB_KEYS" | awk -v kind="$kind" '$NF == kind { print $2, $3 }'
    exit "${STUB_LIST_RC:-0}" ;;
  "ssh-key add")
    case "$*" in
      *"--type authentication"*) [ "${STUB_FAIL_AUTH:-0}" = 0 ] || exit 1 ;;
      *"--type signing"*) touch "$HOME/signing-registered" ;;
    esac ;;
  "config set") mkdir -p "$HOME/.config/gh"; echo 'git_protocol: ssh' > "$HOME/.config/gh/config.yml" ;;
esac
exit 0
"""


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "bw", UNLOCKED_BW % '[ "$1 $2 $3" = "get password github-token" ] && { echo ghp_secret; exit 0; }')
    write_stub(bindir, "gh", GH)
    ssh = Path(env["HOME"], ".ssh")
    ssh.mkdir()
    (ssh / "id_ed25519.pub").write_text(PUB)
    env.update(
        BW_SESSION="x", DOTFILES_MACHINE="testbox", UNITS_NO_SECRETS="0",
        STUB_AUTHED="0", STUB_UNLOCK_RC="0", STUB_LIST_RC="0",
        STUB_SCOPES="admin:public_key, admin:ssh_signing_key", STUB_KEYS="",
    )
    return env


def test_logs_in_with_the_bitwarden_token_and_registers_both_keys(env):
    r = run_unit("github", env, STUB_AUTHED="1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert Path(env["HOME"], "token").read_text() == "ghp_secret"
    c = calls(env)
    assert "ssh-key add" in c and "--title testbox-auth --type authentication" in c and "--title testbox-signing --type signing" in c
    assert "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" in Path(env["HOME"], ".ssh/known_hosts").read_text()


def test_registered_keys_are_not_added_again(env):
    keys = "testbox-auth\tssh-ed25519 AAAAKEYBODY\t2026-01-01\t1\tauthentication\ntestbox-signing\tssh-ed25519 AAAAKEYBODY\t2026-01-01\t2\tsigning\n"
    r = run_unit("github", env, STUB_KEYS=keys)
    assert r.returncode == 0 and "ssh-key add" not in calls(env)
    assert "auth login" not in calls(env)  # already authenticated


def test_only_the_missing_key_type_is_added(env):
    keys = "testbox-auth\tssh-ed25519 AAAAKEYBODY\t2026-01-01\t1\tauthentication\n"
    run_unit("github", env, STUB_KEYS=keys)
    c = calls(env)
    assert "--type signing" in c and "--type authentication" not in c


def test_signing_key_is_registered_even_if_authentication_key_fails(env):
    result = run_unit("github", env, STUB_FAIL_AUTH="1")
    assert result.returncode != 0
    assert Path(env["HOME"], "signing-registered").exists()


def test_token_without_key_scopes_is_partial_and_adds_nothing(env):
    r = run_unit("github", env, STUB_SCOPES="repo, read:org")
    assert r.returncode == 0 and "PARTIAL:" in r.stdout and "ssh-key add" not in calls(env)


def test_locked_vault_does_not_log_in(env):
    r = run_unit("github", env, STUB_AUTHED="1", STUB_UNLOCK_RC="1")
    assert r.returncode == 0 and "PARTIAL: gh not logged in" in r.stdout
    assert "auth login" not in calls(env)


@pytest.mark.parametrize("authed", ["0", "1"])
def test_no_secrets_skips_all_github_and_vault_operations(env, authed):
    r = run_unit("github", env, UNITS_NO_SECRETS="1", STUB_AUTHED=authed)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIPPED: GitHub authentication and SSH key registration" in r.stdout
    assert calls(env) == ""
    assert "github.com ssh-ed25519" in Path(env["HOME"], ".ssh/known_hosts").read_text()


def test_no_secrets_preserves_known_hosts_failure(env):
    Path(env["HOME"], ".ssh/known_hosts").mkdir()
    r = run_unit("github", env, UNITS_NO_SECRETS="1")
    assert r.returncode != 0
    assert "FAIL  github known_hosts" in r.stdout
    assert "SKIPPED: GitHub authentication and SSH key registration" in r.stdout
    assert calls(env) == ""


@pytest.mark.parametrize("authed", ["0", "1"])
def test_gh_config_is_left_for_chezmoi(env, authed):
    config = Path(env["HOME"], ".config/gh/config.yml")
    config.parent.mkdir(parents=True)
    original = "version: 1\ngit_protocol: https\nprompt: enabled\n"
    config.write_text(original)
    r = run_unit("github", env, STUB_AUTHED=authed)
    assert r.returncode == 0, r.stdout + r.stderr
    assert config.read_text() == original
    assert "gh config set" not in calls(env)


@pytest.mark.parametrize("partial_output", ["", "testbox-auth\tssh-ed25519 AAAAKEYBODY\tauthentication\n"])
def test_failed_key_list_never_registers_even_with_partial_output(env, partial_output):
    r = run_unit("github", env, STUB_LIST_RC="1", STUB_KEYS=partial_output)
    assert r.returncode != 0
    assert "registration skipped" in r.stdout
    assert "FAIL  register SSH keys" in r.stdout
    assert "gh api --paginate" in calls(env)
    assert "ssh-key add" not in calls(env)


def test_failed_token_read_does_not_log_in_with_partial_output(env):
    bindir = Path(env["PATH"].split(":")[0])
    write_stub(bindir, "bw", UNLOCKED_BW % '''
if [ "$1 $2 $3" = "get password github-token" ]; then
  echo partial-token
  exit 1
fi
''')
    result = run_unit("github", env, STUB_AUTHED="1")
    assert result.returncode == 0 and "no 'github-token'" in result.stdout
    assert "gh auth login" not in calls(env)
    assert "partial-token" not in result.stdout + result.stderr


def test_unrelated_matching_comment_does_not_count_as_github_key(env):
    known = Path(env["HOME"], ".ssh/known_hosts")
    known.write_text("other.example ssh-ed25519 AAAA github.com ssh-ed25519 "
                     "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    result = run_unit("github", env, UNITS_NO_SECRETS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "\ngithub.com ssh-ed25519 " in known.read_text()


@pytest.mark.parametrize("check", ["0", "1"])
def test_conflicting_github_host_key_is_not_trusted_or_replaced(env, check):
    known = Path(env["HOME"], ".ssh/known_hosts")
    original = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJm\n"
    known.write_text(original)
    result = run_unit("github", env, UNITS_NO_SECRETS="1", UNITS_CHECK=check)
    assert result.returncode != 0 and "conflicting GitHub" in result.stdout
    assert known.read_text() == original


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen not installed")
def test_hashed_existing_github_key_is_not_duplicated(env):
    known = Path(env["HOME"], ".ssh/known_hosts")
    known.write_text("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    subprocess.run(["ssh-keygen", "-H", "-f", str(known)], check=True, capture_output=True)
    original = known.read_text()
    result = run_unit("github", env, UNITS_NO_SECRETS="1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert known.read_text() == original


@pytest.mark.parametrize("check", ["0", "1"])
def test_revoked_pinned_key_is_not_readded(env, check):
    known = Path(env["HOME"], ".ssh/known_hosts")
    original = "@revoked github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
    known.write_text(original)
    result = run_unit("github", env, UNITS_NO_SECRETS="1", UNITS_CHECK=check)
    assert result.returncode != 0 and "revoked" in result.stdout
    assert known.read_text() == original


def test_symlinked_known_hosts_is_not_modified(env):
    known = Path(env["HOME"], ".ssh/known_hosts")
    target = Path(env["HOME"], "custom-known-hosts")
    target.write_text("user settings\n")
    known.symlink_to(target)
    result = run_unit("github", env, UNITS_NO_SECRETS="1")
    assert result.returncode != 0 and "symlinked" in result.stdout
    assert known.is_symlink() and target.read_text() == "user settings\n"
