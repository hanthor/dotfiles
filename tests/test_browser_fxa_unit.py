import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_failed_helper_install_does_not_run_stale_copy(stub_env):
    env, home, profile = prepare(stub_env)
    helper = home / ".local/bin/fxa_signin.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("old helper")
    token = profile / "signedInUser.json"
    token.write_text("existing")
    write_stub(stub_env[0], "install", 'exit 1\n')
    result = run(env)
    assert result.returncode != 0
    assert "helper installation failed" in result.stdout
    assert helper.read_text() == "old helper"
    assert token.read_text() == "existing"
    assert not (home / "signin-captured").exists()
    assert not (home / "bw-calls").exists()


def test_token_symlink_is_not_followed(stub_env):
    env, home, profile = prepare(stub_env)
    target = home / "unrelated"
    target.write_text("custom data")
    target.chmod(0o644)
    (profile / "signedInUser.json").symlink_to(target)
    result = run(env)
    assert result.returncode == 0
    assert "token is a symlink" in result.stdout
    assert target.read_text() == "custom data"
    assert target.stat().st_mode & 0o777 == 0o644
    assert not (home / "signin-captured").exists()


@pytest.mark.parametrize("data,expected", [
    ('{"accountData": {"verified": true}}', 0),
    ('{"accountData": {"verified": false, "sessionToken": "keep"}}', 1),
    ('not valid JSON', 1),
    ('[]', 1),
])
def test_signin_helper_preserves_existing_account_data(tmp_path, data, expected):
    profile = tmp_path / "profile"
    profile.mkdir()
    token = profile / "signedInUser.json"
    token.write_text(data)
    env = dict(os.environ, PROFILE_DIR=str(profile), FXA_EMAIL="person@example.test",
               FXA_PASSWORD="test-password", PYTHONPATH=str(tmp_path))
    result = subprocess.run([sys.executable, str(REPO / "units/browser-fxa/fxa_signin.py")],
                            env=env, text=True, capture_output=True)
    assert result.returncode == expected
    assert token.read_text() == data
    assert "test-password" not in result.stdout + result.stderr


@pytest.mark.parametrize("race", [False, True])
def test_signin_helper_publishes_private_token_without_overwriting_race(tmp_path, race):
    profile = tmp_path / "profile"
    profile.mkdir()
    package = tmp_path / "fxa"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "core.py").write_text('''\
import os
from pathlib import Path

class Session:
    token = b"token"
    uid = "uid"

class Client:
    def __init__(self, url):
        pass

    def login(self, email, password):
        if os.environ.get("CREATE_RACE") == "1":
            (Path(os.environ["PROFILE_DIR"]) / "signedInUser.json").write_text("browser data")
        return Session()
''')
    env = dict(os.environ, PROFILE_DIR=str(profile), FXA_EMAIL="person@example.test",
               FXA_PASSWORD="test-password", FXA_TOTP="", PYTHONPATH=str(tmp_path),
               CREATE_RACE="1" if race else "0")
    result = subprocess.run([sys.executable, str(REPO / "units/browser-fxa/fxa_signin.py")],
                            env=env, text=True, capture_output=True)
    token = profile / "signedInUser.json"
    if race:
        assert result.returncode != 0
        assert token.read_text() == "browser data"
    else:
        assert result.returncode == 0, result.stderr
        assert json.loads(token.read_text())["accountData"]["sessionToken"] == b"token".hex()
        assert token.stat().st_mode & 0o777 == 0o600
    assert not list(profile.glob(".signedInUser.*"))
    assert "test-password" not in result.stdout + result.stderr
