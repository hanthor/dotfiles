from pathlib import Path

from conftest import write_stub
from unit_helpers import calls, run_unit

CURL = 'echo "curl $*" >> "$HOME/calls"\nout=""; while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done\n: > "$out"\nexit "${STUB_CURL_RC:-0}"\n'
UNZIP = 'echo "unzip $*" >> "$HOME/calls"\nd=""; while [ $# -gt 0 ]; do [ "$1" = -d ] && d="$2"; shift; done\n: > "$d/JetBrainsMonoNerdFont-Regular.ttf"\nexit "${STUB_UNZIP_RC:-0}"\n'


def setup(stub_env, desktop):
    bindir, env = stub_env
    write_stub(bindir, "curl", CURL)
    write_stub(bindir, "unzip", UNZIP)
    write_stub(bindir, "fc-cache", 'echo "fc-cache $*" >> "$HOME/calls"\nexit "${STUB_FC_RC:-0}"\n')
    env["DOTFILES_IS_DESKTOP"] = "1" if desktop else "0"
    return env


def test_desktop_installs_the_font_once(stub_env):
    env = setup(stub_env, True)
    r = run_unit("fonts", env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (Path(env["HOME"]) / ".local/share/fonts/JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf").exists()
    assert "fc-cache -f" in calls(env)
    before = calls(env)
    assert run_unit("fonts", env).returncode == 0
    assert calls(env) == before  # second run downloads nothing


def test_non_desktop_downloads_nothing(stub_env):
    env = setup(stub_env, False)
    r = run_unit("fonts", env)
    assert r.returncode == 0 and "curl" not in calls(env)


def test_failed_download_fails_the_unit_without_a_partial_install(stub_env):
    env = setup(stub_env, True)
    r = run_unit("fonts", env, STUB_CURL_RC="22")
    assert r.returncode == 1 and "FAIL  install JetBrains Mono Nerd Font" in r.stdout
    assert not (Path(env["HOME"]) / ".local/share/fonts/JetBrainsMono").exists()


def test_failed_extraction_cannot_leave_a_false_install_marker(stub_env):
    env = setup(stub_env, True)
    font_dir = Path(env["HOME"]) / ".local/share/fonts/JetBrainsMono"
    font_dir.mkdir(parents=True)
    (font_dir / "custom.ttf").write_text("custom font")
    result = run_unit("fonts", env, STUB_UNZIP_RC="1")
    assert result.returncode == 1
    assert not (font_dir / "JetBrainsMonoNerdFont-Regular.ttf").exists()
    assert (font_dir / "custom.ttf").read_text() == "custom font"
    assert run_unit("fonts", env).returncode == 0
    assert (font_dir / "JetBrainsMonoNerdFont-Regular.ttf").exists()


def test_failed_cache_refresh_is_reported_and_retried_without_downloading(stub_env):
    env = setup(stub_env, True)
    result = run_unit("fonts", env, STUB_FC_RC="1")
    assert result.returncode == 1 and "FAIL  font cache" in result.stdout
    before = calls(env)
    result = run_unit("fonts", env, UNITS_CHECK="1")
    assert result.returncode == 0 and "retry JetBrains Mono font cache" in result.stdout
    assert calls(env) == before
    assert run_unit("fonts", env).returncode == 0
    after = calls(env)
    assert after.count("curl ") == before.count("curl ")
    assert after.count("fc-cache -f") == 2
    assert run_unit("fonts", env).returncode == 0
    assert calls(env) == after


def test_failed_desktop_lookup_does_not_skip_font_configuration(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "yq", "exit 2\n")
    result = run_unit("fonts", env, DOTFILES_IS_DESKTOP="", DOTFILES_MACHINE="unknown-test-host")
    assert result.returncode != 0
    assert "curl" not in calls(env)
