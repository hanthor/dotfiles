import importlib.util
import os
import shutil
import socket
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import REPO, write_stub
from unit_helpers import calls, run_unit


@pytest.fixture
def env(stub_env):
    bindir, env = stub_env
    write_stub(bindir, "yq", '''
echo "yq $*" >> "$HOME/calls"
[ "${STUB_YQ_FAIL:-0}" = 1 ] && exit 1
case "$*" in
  *'has('* ) echo "${STUB_DESKTOP:-true}" ;;
  *'.brew_prefix'*) echo /custom/brew ;;
  *'.gnome_enabled_extensions'*host_vars*) echo "${STUB_HOST_EXTENSIONS:-null}" ;;
  *'.gnome_enabled_extensions'*) echo '["canonical@example", "other@example"]' ;;
  *) exit 1 ;;
esac
''')
    write_stub(bindir, "gdbus", 'echo "gdbus $*" >> "$HOME/calls"\nexit "${STUB_BUS_FAIL:-0}"\n')
    write_stub(bindir, "dconf", '''
echo "dconf $* bus=${DBUS_SESSION_BUS_ADDRESS:-unset}" >> "$HOME/calls"
cat > /dev/null
case "$*" in
  *media-keys*) exit "${STUB_KEY_FAIL:-0}" ;;
  *extensions*) exit "${STUB_EXTENSION_FAIL:-0}" ;;
esac
''')
    write_stub(bindir, "gsettings", '''
echo "gsettings $* bus=${DBUS_SESSION_BUS_ADDRESS:-unset}" >> "$HOME/calls"
case "$*" in
  'get org.gnome.Ptyxis default-profile-uuid') echo "'test-uuid'" ;;
  *' custom-command') echo "'${STUB_CURRENT_COMMAND:-/old/fish}'" ;;
  'get org.gnome.Ptyxis font-name') echo "'${STUB_CURRENT_FONT:-old font}'" ;;
esac
exit "${STUB_GSETTINGS_FAIL:-0}"
''')
    write_stub(bindir, "curl", '''
echo "curl $*" >> "$HOME/calls"
[ "${STUB_CURL_FAIL:-0}" = 1 ] && exit 1
while [ "$#" -gt 0 ]; do
  if [ "$1" = -o ]; then printf image > "$2"; exit 0; fi
  shift
done
exit 1
''')
    write_stub(bindir, "sudo", 'echo "sudo $*" >> "$HOME/calls"\nexit "${STUB_SUDO_FAIL:-0}"\n')
    write_stub(bindir, "python3", 'echo "python3 $*" >> "$HOME/calls"\nexit "${STUB_SUDO_FAIL:-0}"\n')
    write_stub(bindir, "grdctl", '''
echo "grdctl $*" >> "$HOME/calls"
[ "$*" = "rdp status" ] && echo "Status: enabled"
exit "${STUB_GRD_FAIL:-0}"
''')
    write_stub(bindir, "systemctl", 'echo "systemctl $* runtime=${XDG_RUNTIME_DIR:-unset}" >> "$HOME/calls"\nexit "${STUB_SYSTEMCTL_FAIL:-0}"\n')
    env.update(DOTFILES_IS_DESKTOP="1", DOTFILES_MACHINE="gnome-test", DBUS_SESSION_BUS_ADDRESS="unix:path=/test/user-bus")
    return env


def test_desktop_uses_canonical_assets_and_live_user_session(env):
    result = run_unit("gnome", env)
    assert result.returncode == 0, result.stdout + result.stderr
    home = Path(env["HOME"])
    files = REPO / "units/gnome"
    keys = home / ".config/dconf/gnome-keybindings.ini"
    assert keys.read_bytes() == (files / "gnome-keybindings.ini").read_bytes()
    assert stat.S_IMODE(keys.stat().st_mode) == 0o644
    extension = home / ".local/share/gnome-shell/extensions/papershell@lalovene.github.com/extension.js"
    assert extension.read_bytes() == (files / "extensions/papershell@lalovene.github.com/extension.js").read_bytes()
    assert stat.S_IMODE(extension.stat().st_mode) == 0o644
    log = calls(env)
    assert "dconf load /org/gnome/settings-daemon/plugins/media-keys/ bus=unix:path=/test/user-bus" in log
    assert "dconf load /org/gnome/shell/extensions/ bus=unix:path=/test/user-bus" in log
    assert 'gsettings set org.gnome.shell enabled-extensions ["canonical@example", "other@example"]' in log
    assert "group_vars/all.yml" in log
    assert "custom-command /custom/brew/bin/fish" in log
    assert "systemctl --user enable --now gnome-remote-desktop.service" in log
    assert "grdctl rdp enable" not in log
    assert "gnome-avatar.py" in log

    mtime = extension.stat().st_mtime_ns
    first_keys = log.count("dconf load /org/gnome/settings-daemon/plugins/media-keys/")
    second = run_unit("gnome", env, STUB_CURRENT_COMMAND="/custom/brew/bin/fish", STUB_CURRENT_FONT="JetBrainsMono Nerd Font 12")
    assert second.returncode == 0, second.stdout + second.stderr
    assert extension.stat().st_mtime_ns == mtime
    assert calls(env).count("dconf load /org/gnome/settings-daemon/plugins/media-keys/") == first_keys
    assert calls(env).count("custom-command /custom/brew/bin/fish") == 1


def test_failed_keybinding_load_is_reported_and_retried(env):
    result = run_unit("gnome", env, STUB_KEY_FAIL="1")
    assert result.returncode == 1
    assert "FAIL  load GNOME keybindings in user session" in result.stdout
    marker = Path(env["HOME"]) / ".config/dconf/.gnome-keybindings.pending"
    assert marker.exists()
    assert "dconf load /org/gnome/shell/extensions/" in calls(env)
    result = run_unit("gnome", env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()
    assert calls(env).count("dconf load /org/gnome/settings-daemon/plugins/media-keys/") == 2


@pytest.mark.parametrize("extra", [
    {"DBUS_SESSION_BUS_ADDRESS": "", "XDG_RUNTIME_DIR": ""},
    {"DBUS_SESSION_BUS_ADDRESS": "autolaunch:", "XDG_RUNTIME_DIR": ""},
    {"STUB_BUS_FAIL": "1"},
])
def test_missing_or_unreachable_session_is_not_treated_as_success(env, extra):
    bash_env = Path(env["HOME"]) / "no-runtime-socket.bash"
    bash_env.write_text('function [() { if [[ "${1:-}" == -S && "${2:-}" == "/run/user/$UID/bus" ]]; then return 1; fi; builtin [ "$@"; }\n')
    result = run_unit("gnome", env, BASH_ENV=str(bash_env), **extra)
    assert result.returncode == 1
    assert "GNOME user D-Bus session unavailable" in result.stdout
    assert "FAIL  load GNOME keybindings" in result.stdout
    assert Path(env["HOME"], ".config/dconf/.gnome-keybindings.pending").exists()
    assert "dconf load" not in calls(env)
    assert "gsettings " not in calls(env)
    assert "systemctl " not in calls(env)


def test_existing_runtime_bus_is_used_without_autolaunch(env, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with socket.socket(socket.AF_UNIX) as bus:
        bus.bind(str(runtime / "bus"))
        result = run_unit("gnome", env, DBUS_SESSION_BUS_ADDRESS="", XDG_RUNTIME_DIR=str(runtime))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"bus=unix:path={runtime}/bus" in calls(env)


@pytest.mark.parametrize("address", ["", "unix:path=/existing/session"])
def test_ssh_discovers_user_runtime_without_overriding_inherited_bus(env, address):
    # Stub only the socket check so this never depends on the test host's /run.
    bash_env = Path(env["HOME"]) / "runtime-socket.bash"
    bash_env.write_text('function [() { if [[ "${1:-}" == -S && "${2:-}" == "/run/user/$UID/bus" ]]; then return 0; fi; builtin [ "$@"; }\n')
    result = run_unit("gnome", env, BASH_ENV=str(bash_env), XDG_RUNTIME_DIR="", DBUS_SESSION_BUS_ADDRESS=address)
    assert result.returncode == 0, result.stdout + result.stderr
    runtime = f"/run/user/{os.getuid()}"
    expected_bus = address or f"unix:path={runtime}/bus"
    assert f"dconf load /org/gnome/shell/extensions/ bus={expected_bus}" in calls(env)
    assert f"systemctl --user enable --now gnome-remote-desktop.service runtime={runtime}" in calls(env)


def test_optional_session_failures_are_visible(env):
    result = run_unit("gnome", env, STUB_EXTENSION_FAIL="1", STUB_GSETTINGS_FAIL="1", STUB_GRD_FAIL="1", STUB_SYSTEMCTL_FAIL="1")
    assert result.returncode == 0
    assert "warn  Ptyxis profile" in result.stdout
    assert "warn  load GNOME extension settings" in result.stdout
    assert "warn  enable GNOME extensions" in result.stdout
    assert "warn  enable GNOME RDP protocol" in result.stdout
    assert "warn  enable GNOME Remote Desktop user service" in result.stdout


@pytest.mark.parametrize("failure", [{"STUB_CURL_FAIL": "1"}, {"STUB_SUDO_FAIL": "1"}])
def test_avatar_failure_fails_without_suppressing_other_steps(env, failure):
    result = run_unit("gnome", env, **failure)
    assert result.returncode == 1
    assert "FAIL  AccountsService avatar" in result.stdout
    assert "dconf load /org/gnome/shell/extensions/" in calls(env)


def test_non_desktop_and_profile_gates(env, tmp_path):
    result = run_unit("gnome", env, DOTFILES_IS_DESKTOP="0")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not Path(env["HOME"], "calls").exists()
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars/phone.yml").write_text("skip_gnome: true\n")
    result = run_unit("gnome", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="phone")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    (repo / "host_vars/phone.yml").write_text("machine_profile: vm-test\n")
    result = run_unit("gnome", env, DOTFILES_DIR=str(repo), DOTFILES_MACHINE="phone")
    assert result.returncode == 0 and "SKIPPED" in result.stdout
    assert not Path(env["HOME"], "calls").exists()


def test_inventory_error_and_missing_yq_do_not_silently_skip(env, tmp_path):
    result = run_unit("gnome", env, DOTFILES_IS_DESKTOP="", STUB_YQ_FAIL="1")
    assert result.returncode == 1 and "FAIL  determine desktop membership" in result.stdout
    bindir = tmp_path / "limited-bin"
    bindir.mkdir()
    for binary in ("bash", "dirname", "sed", "head", "cat"):
        (bindir / binary).symlink_to(shutil.which(binary))
    result = run_unit("gnome", env, DOTFILES_IS_DESKTOP="", PATH=str(bindir))
    assert result.returncode == 1 and "FAIL  determine desktop membership" in result.stdout


def test_host_extension_override_and_configuration_failure(env, tmp_path):
    repo = tmp_path / "repo"
    (repo / "host_vars").mkdir(parents=True)
    (repo / "host_vars/gnome-test.yml").write_text("brew_prefix: /host/brew\ngnome_enabled_extensions:\n  - host@example\n")
    (repo / "units").mkdir(parents=True)
    (repo / "units/gnome").symlink_to(REPO / "units/gnome")
    result = run_unit("gnome", env, DOTFILES_DIR=str(repo), STUB_HOST_EXTENSIONS='["host@example"]')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'gsettings set org.gnome.shell enabled-extensions ["host@example"]' in calls(env)
    assert "custom-command /host/brew/bin/fish" in calls(env)
    result = run_unit("gnome", env, STUB_YQ_FAIL="1")
    assert result.returncode == 1 and "FAIL  read GNOME configuration" in result.stdout


def load_avatar_helper():
    spec = importlib.util.spec_from_file_location("gnome_avatar", REPO / "units/gnome-avatar.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_avatar_updates_accounts_and_gdm_idempotently(tmp_path, monkeypatch):
    helper = load_avatar_helper()
    icons = tmp_path / "icons"
    users = tmp_path / "users"
    icons.mkdir()
    users.mkdir()
    account = users / "james"
    account.write_text("# retained\n[User]\nName=James\nIcon=/old\nIcon=/duplicate\n[Other]\nIcon=untouched\n")
    source = tmp_path / "source.png"
    source.write_bytes(b"avatar")
    monkeypatch.setattr(helper, "ICON", icons / "james")
    monkeypatch.setattr(helper, "ACCOUNT", account)
    monkeypatch.setattr(helper, "GDM_CACHE", tmp_path / "gdm/.cache")
    monkeypatch.setattr(helper.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.getuid()))
    monkeypatch.setattr(helper.grp, "getgrnam", lambda name: SimpleNamespace(gr_gid=os.getgid()))
    helper.install_avatar(source)
    cache = tmp_path / "gdm/.cache/james"
    assert cache.read_bytes() == (icons / "james").read_bytes() == b"avatar"
    assert account.read_text() == "# retained\n[User]\nName=James\nIcon=/var/lib/AccountsService/icons/james\n[Other]\nIcon=untouched\n"
    for path in (cache, icons / "james", account):
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    before = [(p.stat().st_ino, p.stat().st_mtime_ns) for p in (cache, icons / "james", account)]
    helper.install_avatar(source)
    assert before == [(p.stat().st_ino, p.stat().st_mtime_ns) for p in (cache, icons / "james", account)]


def test_avatar_without_gdm_creates_user_section(tmp_path, monkeypatch):
    helper = load_avatar_helper()
    (tmp_path / "icons").mkdir()
    (tmp_path / "users").mkdir()
    source = tmp_path / "source.png"
    source.write_bytes(b"avatar")
    monkeypatch.setattr(helper, "ICON", tmp_path / "icons/james")
    monkeypatch.setattr(helper, "ACCOUNT", tmp_path / "users/james")
    monkeypatch.setattr(helper, "GDM_CACHE", tmp_path / "gdm/.cache")
    def no_gdm(name):
        raise KeyError(name)
    monkeypatch.setattr(helper.pwd, "getpwnam", no_gdm)
    helper.install_avatar(source)
    assert (tmp_path / "users/james").read_text() == "[User]\nIcon=/var/lib/AccountsService/icons/james\n"
    assert not (tmp_path / "gdm").exists()
