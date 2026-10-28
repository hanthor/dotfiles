import shutil
import subprocess

import pytest

from conftest import REPO, write_stub

NASTY = "pa'ss\\word\"$ord"

BW_STUB = """\
if [ "$1 $2" = "unlock --check" ]; then exit "${STUB_UNLOCK_RC:-0}"; fi
[ "$1" = get ] || exit 1
case "$2 $3" in
  "password deepseek-api-key") printf '%s\\n' "$STUB_DEEPSEEK" ;;
  "notes forgejo") printf 'Name: x\\nAPI Token: forge123\\n' ;;
  "password tavily-api-key") printf 'tav456\\n' ;;
  *) exit 1 ;;
esac
"""


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "bw", BW_STUB)
    env.update(BW_SESSION="x", DOTFILES_DIR=str(REPO), STUB_DEEPSEEK=NASTY, BREW_PREFIX="/nonexistent")
    return env


def run(env, **extra):
    return subprocess.run(
        ["bash", str(REPO / "units/shell-ai.sh")], env={**env, **extra}, capture_output=True, text=True
    )


def home(env):
    from pathlib import Path

    return Path(env["HOME"])


def test_secrets_round_trip_and_modes(env):
    r = run(env)
    assert r.returncode == 0, r.stdout + r.stderr
    sh = home(env) / ".config/shell/secrets.sh"
    fish = home(env) / ".config/fish/conf.d/secrets.fish"
    assert sh.stat().st_mode & 0o777 == 0o600 and fish.stat().st_mode & 0o777 == 0o600
    out = subprocess.run(
        ["bash", "-c", f'. {sh}; printf "%s\\n%s\\n%s" "$DEEPSEEK_API_KEY" "$FORGEJO_TOKEN" "$TAVILY_API_KEY"'],
        capture_output=True,
        text=True,
    ).stdout
    assert out == f"{NASTY}\nforge123\ntav456"
    assert "set -gx FORGEJO_TOKEN 'forge123'" in fish.read_text()
    assert "2706eda5-e8ad-43df-9838-b4e00167e95d" in fish.read_text()
    assert NASTY not in r.stdout + r.stderr


def test_missing_item_still_writes_the_others(env):
    r = run(env, STUB_DEEPSEEK="")
    assert r.returncode == 0
    text = (home(env) / ".config/shell/secrets.sh").read_text()
    assert "DEEPSEEK_API_KEY" not in text
    assert "FORGEJO_TOKEN='forge123'" in text


@pytest.mark.parametrize("extra", [{"STUB_UNLOCK_RC": "1"}, {"UNITS_NO_SECRETS": "1"}])
def test_locked_or_nosecrets_leaves_files_untouched(env, extra):
    sh = home(env) / ".config/shell/secrets.sh"
    sh.parent.mkdir(parents=True)
    sh.write_text("previous\n")
    r = run(env, **extra)
    assert r.returncode == 0
    assert "SKIPPED:" in r.stdout
    assert sh.read_text() == "previous\n"


def test_failed_secret_read_does_not_export_partial_stdout(env):
    bindir = env["PATH"].split(":")[0]
    write_stub(bindir, "bw", '''
if [ "$1 $2" = "unlock --check" ]; then exit 0; fi
case "$2 $3" in
  "password deepseek-api-key") echo partial-secret; exit 1 ;;
  "password tavily-api-key") echo tav456; exit 0 ;;
esac
exit 1
''')
    result = run(env)
    assert result.returncode == 0
    assert "DEEPSEEK_API_KEY" not in (home(env) / ".config/shell/secrets.sh").read_text()
    assert "partial-secret" not in result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish not installed")
def test_fish_secret_round_trips_quotes_and_backslashes(env):
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    source = str(home(env) / ".config/fish/conf.d/secrets.fish")
    fish = subprocess.run(["fish", "--no-config", "-c", 'source "$SECRET_FILE"; printf "%s" "$DEEPSEEK_API_KEY"'],
                          env={**env, "SECRET_FILE": source}, capture_output=True, text=True)
    assert fish.returncode == 0, fish.stderr
    assert fish.stdout == NASTY


@pytest.mark.skipif(shutil.which("fish") is None or shutil.which("jq") is None,
                    reason="fish and jq required")
@pytest.mark.parametrize("mode,expected", [("failed", "stored-kiro"), ("null", "stored-kiro"),
                                           ("valid", "refreshed-kiro")])
def test_fish_refresh_keeps_stored_key_when_vault_read_fails(env, tmp_path, mode, expected):
    result = run(env)
    assert result.returncode == 0, result.stdout + result.stderr
    source = home(env) / ".config/fish/conf.d/secrets.fish"
    text = source.read_text().replace("/tmp/bw_session", "$TEST_BW_SESSION_FILE")
    source.write_text("set -gx KIRO_API_KEY stored-kiro\n" + text)
    session = tmp_path / "session"
    session.write_text("session-value")
    write_stub(env["PATH"].split(":")[0], "bw", '''
printf '%s' "$BW_SESSION" > "$HOME/refresh-session"
printf '%s' "$*" > "$HOME/refresh-args"
case "$REFRESH_MODE" in
  failed) echo '{"notes":"bad-partial"}'; exit 1 ;;
  null) echo '{"notes":null}'; exit 0 ;;
  valid) echo '{"notes":"refreshed-kiro"}'; exit 0 ;;
esac
''')
    fish = subprocess.run(["fish", "--no-config", "-c", 'source "$SECRET_FILE"; printf "%s" "$KIRO_API_KEY"'],
                          env={**env, "SECRET_FILE": str(source), "TEST_BW_SESSION_FILE": str(session),
                               "REFRESH_MODE": mode}, capture_output=True, text=True)
    assert fish.returncode == 0, fish.stderr
    assert fish.stdout == expected
    assert (home(env) / "refresh-session").read_text() == "session-value"
    assert "session-value" not in (home(env) / "refresh-args").read_text()
