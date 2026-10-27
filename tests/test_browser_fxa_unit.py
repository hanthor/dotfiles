import json
import subprocess
from pathlib import Path

from conftest import REPO, write_stub


UNIT = REPO / "units/browser-fxa.sh"


def prepare(stub_env):
    bindir, env = stub_env
    home = Path(env["HOME"])
    env.update(DOTFILES_DIR=str(REPO), DOTFILES_MACHINE="himachal", DOTFILES_IS_DESKTOP="1", BW_SESSION="session")
    write_stub(bindir, "yq", '''
python3 - "$@" <<'PY'
import sys, yaml
key = sys.argv[2].split()[0].lstrip('.')
with open(sys.argv[3]) as f:
    data = yaml.safe_load(f) or {}
value = data.get(key, '__UNSET__')
print('__UNSET__' if value is None else value)
PY
''')
    write_stub(bindir, "bw", '''
printf '%s\\n' "$*" >> "$HOME/bw-calls"
case "$1" in
  unlock) [ "${BW_LOCKED:-0}" != 1 ] ;;
  list) printf '%s' "$BW_ITEMS" ;;
  get) printf '%s' '123456' ;;
  *) exit 1 ;;
esac
''')
    venv_bin = home / ".local/venvs/fxa/bin"
    venv_bin.mkdir(parents=True)
    write_stub(venv_bin, "python", '''
[ "$1" != -c ] || exit 0
printf '%s\\n' "$FXA_EMAIL" "$FXA_PASSWORD" "$FXA_TOTP" > "$HOME/signin-captured"
printf '%s' 'session-data' > "$PROFILE_DIR/signedInUser.json"
''')
    base = home / ".var/app/app.zen_browser.zen/.zen"
    profile = base / "profile.default"
    profile.mkdir(parents=True)
    (base / "profiles.ini").write_text("[Profile0]\nName=default\nIsRelative=1\nPath=profile.default\nDefault=1\n")
    env["BW_ITEMS"] = json.dumps([
        {"id": "wrong", "login": {"username": "other@example.test", "password": "other-secret"}},
        {"id": "correct", "login": {"username": "jreilly1821@gmail.com", "password": "s'ec ret"}},
    ])
    return env, home, profile


def run(env):
    return subprocess.run(["bash", str(UNIT)], env=env, text=True, capture_output=True)


def test_selects_exact_account_and_keeps_tokens_private(stub_env):
    env, home, profile = prepare(stub_env)
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / "signin-captured").read_text().splitlines() == ["jreilly1821@gmail.com", "s'ec ret", "123456"]
    assert (profile / "signedInUser.json").read_text() == "session-data"
    assert (profile / "signedInUser.json").stat().st_mode & 0o777 == 0o600
    assert "get totp correct" in (home / "bw-calls").read_text()
    assert "s'ec ret" not in result.stdout + result.stderr


def test_mismatched_account_never_used(stub_env):
    env, home, profile = prepare(stub_env)
    env["BW_ITEMS"] = json.dumps([{"id": "wrong", "login": {"username": "other", "password": "do-not-leak"}}])
    (profile / "signedInUser.json").write_text("existing")
    result = run(env)
    assert result.returncode == 0
    assert "username mismatch" in result.stdout
    assert "do-not-leak" not in result.stdout + result.stderr
    assert (profile / "signedInUser.json").read_text() == "existing"
    assert not (home / "signin-captured").exists()


def test_no_secrets_preserves_profile_and_never_calls_bitwarden(stub_env):
    env, home, profile = prepare(stub_env)
    env["UNITS_NO_SECRETS"] = "1"
    (profile / "signedInUser.json").write_text("existing")
    result = run(env)
    assert result.returncode == 0
    assert "PARTIAL:" in result.stdout
    assert (profile / "signedInUser.json").read_text() == "existing"
    assert not (home / "bw-calls").exists()
    assert not (home / "signin-captured").exists()


def test_locked_vault_leaves_existing_account_untouched(stub_env):
    env, home, profile = prepare(stub_env)
    env["BW_LOCKED"] = "1"
    (profile / "signedInUser.json").write_text("existing")
    result = run(env)
    assert result.returncode == 0
    assert "PARTIAL:" in result.stdout
    assert (profile / "signedInUser.json").read_text() == "existing"
    assert not (home / "signin-captured").exists()
    assert "list" not in (home / "bw-calls").read_text()


def test_missing_default_profile_is_not_created(stub_env):
    env, home, profile = prepare(stub_env)
    (profile.parent / "profiles.ini").write_text(
        "[Profile0]\nIsRelative=1\nPath=missing.default\nDefault=1\n"
    )
    result = run(env)
    assert result.returncode == 0
    assert "default profile does not exist" in result.stdout
    assert not (profile.parent / "missing.default").exists()
    assert not (home / "signin-captured").exists()
