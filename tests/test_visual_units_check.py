"""Read-only inspection coverage for the visual desktop units."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from conftest import REPO, write_stub
from unit_helpers import run_unit


@pytest.fixture
def visual(stub_env, tmp_path):
    bindir, env = stub_env
    home = Path(env['HOME'])
    repo = tmp_path / 'repo'
    (repo / 'units').mkdir(parents=True)
    (repo / 'host_vars').mkdir()
    (repo / 'group_vars').mkdir()
    for unit in ('bluefin', 'gnome', 'zen-browser'):
        (repo / 'units' / unit).symlink_to(REPO / 'units' / unit, target_is_directory=True)
    # Keep AccountsService inspection isolated from the host's real account.
    (repo / 'units/gnome-avatar.py').write_text('''\
import os
from pathlib import Path
ICON = Path(os.environ['HOME']) / 'account-icon'
ACCOUNT = Path(os.environ['HOME']) / 'account-data'
GDM_CACHE = Path(os.environ['HOME']) / 'gdm-cache'
def account_with_icon(text):
    return '[User]\\nIcon=/example\\n'
''')
    system_policy = '/var/lib/flatpak/app/app.zen_browser.zen/current/active/files/zen/distribution/policies.json'
    bluefin_wrapper = tmp_path / 'bluefin-check-wrapper.py'
    bluefin_wrapper.write_text('''\
import os
import sys
program = sys.stdin.read().replace("Path('/etc/sysctl.d/99-zram.conf')", 'Path(' + repr(os.environ['CHECK_ZRAM']) + ')')
exec(compile(program, '<stdin>', 'exec'))
''')
    write_stub(bindir, 'python3', f'''\
args=("$@")
if [ "${{args[0]:-}}" = - ] && [ "${{args[1]:-}}" = "$DOTFILES_DIR/units/bluefin" ]; then
  exec '{sys.executable}' "$CHECK_BLUEFIN_WRAPPER" "${{args[@]:1}}"
fi
if [ "${{args[1]:-}}" = '{system_policy}' ]; then args[1]="$CHECK_SYSTEM_POLICY"; fi
exec '{sys.executable}' "${{args[@]}}"
''')
    write_stub(bindir, 'yq', '''\
case "$*" in
  *'.brew_prefix'*) echo /custom/brew ;;
  *'.gnome_enabled_extensions'*) echo '[]' ;;
  *'has('*) echo true ;;
  *) exit 1 ;;
esac
''')
    write_stub(bindir, 'grep', '''\
if [ "${2:-}" = Bluefin ] && [ "${3:-}" = /etc/os-release ]; then exit 1; fi
exec /usr/bin/grep "$@"
''')
    write_stub(bindir, 'gdbus', '[ "${FAIL_SESSION:-0}" = 0 ]\n')
    write_stub(bindir, 'gsettings', '''\
echo "gsettings $*" >> "$CHECK_LOG"
[ "${FAIL_GSETTINGS:-0}" = 0 ] || exit 1
case "$*" in
  'get org.gnome.desktop.interface color-scheme') echo "'prefer-dark'" ;;
  'get org.gnome.Ptyxis default-profile-uuid') echo "'profile'" ;;
  'get org.gnome.Ptyxis.Profile:/org/gnome/ptyxis/profiles/profile/ custom-command') echo "'/custom/brew/bin/fish'" ;;
  'get org.gnome.Ptyxis font-name') echo "'JetBrainsMono Nerd Font 12'" ;;
  'get org.gnome.shell enabled-extensions') echo '@as []' ;;
  'get org.gnome.shell favorite-apps') if [ -n "${CHECK_DOCK:-}" ]; then echo "$CHECK_DOCK"; else echo "['org.mozilla.firefox.desktop']"; fi ;;
  'get org.gnome.desktop.background picture-uri'|'get org.gnome.desktop.background picture-uri-dark') echo "''" ;;
  *) exit 91 ;;
esac
''')
    write_stub(bindir, 'dconf', '''\
echo "dconf $*" >> "$CHECK_LOG"
[ "$1" = dump ] || exit 91
[ -n "${CHECK_DCONF:-}" ] && cat "$CHECK_DCONF"
exit 0
''')
    write_stub(bindir, 'systemctl', '''\
echo "systemctl $*" >> "$CHECK_LOG"
[ "$1 $2" = '--user show' ] || exit 91
[ "${FAIL_SYSTEMCTL:-0}" = 0 ] || exit 1
printf 'LoadState=loaded\\nUnitFileState=disabled\\nActiveState=inactive\\n'
''')
    write_stub(bindir, 'gnome-extensions', '''\
echo "gnome-extensions $*" >> "$CHECK_LOG"
[ "$1" = list ] || exit 91
''')
    write_stub(bindir, 'grdctl', '''\
echo "grdctl $*" >> "$CHECK_LOG"
[ "$*" = 'rdp status' ] || exit 91
printf 'Status: enabled\\nPassword: private-test-password\\n'
''')
    write_stub(bindir, 'xdg-mime', '''\
echo "xdg-mime $*" >> "$CHECK_LOG"
[ "$1 $2" = 'query default' ] || exit 91
[ "${FAIL_MIME:-0}" = 0 ] || exit 1
echo "${CHECK_MIME:-other.desktop}"
''')
    for name in ('curl', 'wget', 'podman', 'unzip', 'sudo', 'install', 'fc-cache', 'sysctl', 'mktemp',
                 'mkdir', 'chmod', 'rm', 'cp', 'mv', 'touch'):
        write_stub(bindir, name, 'echo "FORBIDDEN $0 $*" >> "$CHECK_LOG"\nexit 91\n')
    env.update(DOTFILES_DIR=str(repo), DOTFILES_MACHINE='visual-check', DOTFILES_IS_DESKTOP='1',
               UNITS_CHECK='1', DBUS_SESSION_BUS_ADDRESS='unix:path=/test/bus',
               CHECK_LOG=str(tmp_path / 'calls'), CHECK_SYSTEM_POLICY=str(tmp_path / 'system-policy.json'),
               CHECK_ZRAM=str(tmp_path / 'zram.conf'), CHECK_BLUEFIN_WRAPPER=str(bluefin_wrapper))
    return env, repo


def inspect(unit, env, **extra):
    return run_unit(unit, env, DOTFILES_DIR=env['DOTFILES_DIR'], **extra)


def snapshot(path):
    result = {}
    for entry in [path, *sorted(path.rglob('*'))]:
        info = entry.lstat()
        result[str(entry.relative_to(path))] = (
            stat.S_IMODE(info.st_mode), info.st_mtime_ns,
            entry.read_bytes() if entry.is_file() else None,
            os.readlink(entry) if entry.is_symlink() else None,
        )
    return result


def assert_read_only(env, before):
    assert snapshot(Path(env['HOME'])) == before
    assert not (Path(env['DOTFILES_DIR']) / 'units/__pycache__').exists()
    log = Path(env['CHECK_LOG'])
    text = log.read_text() if log.exists() else ''
    assert 'FORBIDDEN' not in text
    assert 'gsettings set ' not in text
    assert 'dconf load ' not in text
    assert 'systemctl --user enable' not in text
    assert 'grdctl rdp enable' not in text
    assert 'xdg-mime default' not in text


def test_bluefin_reports_local_and_offline_plans_without_mutating(visual):
    env, _ = visual
    home = Path(env['HOME'])
    old = home / '.local/bin/tailvm'
    old.parent.mkdir(parents=True)
    old.write_text('old binary')
    before = snapshot(home)
    result = inspect('bluefin', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WOULD remove retired tailvm file' in result.stdout
    assert 'WOULD update wallpaper rotation script' in result.stdout
    assert 'WOULD enable and start wallpaper timer' in result.stdout
    assert 'remote image and archives not inspected' in result.stdout
    assert 'WOULD install GNOME extension' in result.stdout
    assert_read_only(env, before)


def test_bluefin_inspection_errors_are_not_success(visual):
    env, _ = visual
    before = snapshot(Path(env['HOME']))
    result = inspect('bluefin', env, FAIL_SYSTEMCTL='1', DBUS_SESSION_BUS_ADDRESS='autolaunch:')
    assert result.returncode != 0
    assert 'FAIL  inspect GNOME session' in result.stdout
    assert 'FAIL  inspect wallpaper timer' in result.stdout
    assert_read_only(env, before)
    assert 'gsettings ' not in Path(env['CHECK_LOG']).read_text()


def test_gnome_reports_deployment_and_session_drift_without_mutation(visual):
    env, _ = visual
    home = Path(env['HOME'])
    before = snapshot(home)
    result = inspect('gnome', env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WOULD update GNOME keybindings file' in result.stdout
    assert 'WOULD load GNOME keybindings' in result.stdout
    assert 'WOULD create or fix extension' in result.stdout
    assert 'WOULD load GNOME extension settings' in result.stdout
    assert 'WOULD enable and start GNOME Remote Desktop' in result.stdout
    assert 'remote image not inspected' in result.stdout
    assert 'private-test-password' not in result.stdout + result.stderr
    assert_read_only(env, before)


def test_gnome_session_errors_do_not_create_pending_marker(visual):
    env, _ = visual
    home = Path(env['HOME'])
    before = snapshot(home)
    result = inspect('gnome', env, FAIL_SESSION='1')
    assert result.returncode != 0
    assert 'FAIL  inspect GNOME user session' in result.stdout
    assert not (home / '.config/dconf/.gnome-keybindings.pending').exists()
    assert_read_only(env, before)


def test_gnome_invalid_dconf_does_not_disclose_values(visual, tmp_path):
    env, _ = visual
    data = tmp_path / 'broken-dconf'
    data.write_text('[unclosed-secret-value\n')
    before = snapshot(Path(env['HOME']))
    result = inspect('gnome', env, CHECK_DCONF=str(data))
    assert result.returncode != 0
    assert 'FAIL  inspect GNOME user session' in result.stdout
    assert 'unclosed-secret-value' not in result.stdout + result.stderr
    assert_read_only(env, before)
    assert 'systemctl --user show' in Path(env['CHECK_LOG']).read_text()


def zen_profile(home):
    base = home / '.var/app/app.zen_browser.zen/.zen'
    profile = base / 'abc.default'
    profile.mkdir(parents=True)
    (base / 'profiles.ini').write_text('[Profile0]\nIsRelative=1\nPath=abc.default\n')
    return profile


def test_zen_reports_drift_without_writing_preferences_or_policies(visual):
    env, _ = visual
    home = Path(env['HOME'])
    profile = zen_profile(home)
    (profile / 'user.js').write_text('user_pref("local", true);\n')
    before = snapshot(home)
    result = inspect('zen-browser', env)
    assert result.returncode == 0, result.stdout + result.stderr
    for expected in ('WOULD update GNOME dock', 'WOULD set default browser',
                     'WOULD update Zen profile preferences', 'WOULD update Flatpak Zen policy',
                     'WOULD update user Zen policy'):
        assert expected in result.stdout
    assert_read_only(env, before)


def test_zen_converged_preferences_and_user_policy_are_recognized(visual):
    env, _ = visual
    home = Path(env['HOME'])
    profile = zen_profile(home)
    (profile / 'user.js').write_text((REPO / 'units/zen-browser/user.js').read_text())
    (profile / 'user.js').chmod(0o644)
    policy = home / '.zen/distribution/policies.json'
    policy.parent.mkdir(parents=True)
    data = json.loads((REPO / 'units/zen-browser/policies.json').read_text())
    policy.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    policy.chmod(0o644)
    before = snapshot(home)
    result = inspect('zen-browser', env, CHECK_DOCK="['app.zen_browser.zen.desktop']",
                     CHECK_MIME='app.zen_browser.zen.desktop')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'OK GNOME dock' in result.stdout
    assert 'OK Zen profile preferences' in result.stdout
    assert 'OK user Zen policy' in result.stdout
    assert 'WOULD set default browser' not in result.stdout
    assert_read_only(env, before)


def test_zen_reports_inspection_errors_without_exposing_policy(visual):
    env, _ = visual
    home = Path(env['HOME'])
    profile = zen_profile(home)
    (profile / 'user.js').write_text('// BEGIN dotfiles Zen preferences\nprivate-value\n')
    policy = home / '.zen/distribution/policies.json'
    policy.parent.mkdir(parents=True)
    policy.write_text('private-policy-value')
    before = snapshot(home)
    result = inspect('zen-browser', env, FAIL_MIME='1')
    assert result.returncode != 0
    assert 'FAIL  inspect default browser' in result.stdout
    assert 'FAIL  Zen profile preferences' in result.stdout
    assert 'FAIL  user Zen policy' in result.stdout
    assert 'private-value' not in result.stdout + result.stderr
    assert 'private-policy-value' not in result.stdout + result.stderr
    assert_read_only(env, before)


@pytest.mark.parametrize('unit', ['bluefin', 'gnome', 'zen-browser'])
def test_non_desktop_check_has_no_side_effects(visual, unit):
    env, _ = visual
    before = snapshot(Path(env['HOME']))
    result = inspect(unit, env, DOTFILES_IS_DESKTOP='0')
    assert result.returncode == 0
    assert 'not a desktop' in result.stdout
    assert_read_only(env, before)
    assert not Path(env['CHECK_LOG']).exists()


def test_bluefin_missing_source_is_an_inspection_error(visual):
    env, repo = visual
    assets = repo / 'units/bluefin'
    assets.unlink()
    assets.mkdir()
    before = snapshot(Path(env['HOME']))
    result = inspect('bluefin', env)
    assert result.returncode != 0
    assert 'FAIL  inspect Bluefin files and wallpaper' in result.stdout
    assert_read_only(env, before)


def test_zen_missing_profile_still_inspects_dock_without_writes(visual):
    env, _ = visual
    before = snapshot(Path(env['HOME']))
    result = inspect('zen-browser', env)
    assert result.returncode == 0
    assert 'WOULD update GNOME dock' in result.stdout
    assert 'profiles.ini not found' in result.stdout
    assert_read_only(env, before)


def test_zen_does_not_autolaunch_a_session(visual):
    env, _ = visual
    before = snapshot(Path(env['HOME']))
    result = inspect('zen-browser', env, DBUS_SESSION_BUS_ADDRESS='autolaunch:')
    assert result.returncode != 0
    assert 'FAIL  inspect GNOME dock' in result.stdout
    assert_read_only(env, before)
    assert not Path(env['CHECK_LOG']).exists()


def test_zen_gio_fallback_checks_default_without_changing_it(visual, tmp_path):
    env, _ = visual
    bindir = Path(env['PATH'].split(':')[0])
    write_stub(bindir, 'gio', '''\
echo "gio $*" >> "$CHECK_LOG"
[ "$1" = mime ] && [ "$#" = 2 ] || exit 91
printf 'Default application for “%s”: app.zen_browser.zen.desktop\\nRegistered applications:\\n' "$2"
''')
    bash_env = tmp_path / 'no-xdg-mime.bash'
    bash_env.write_text('command() { if [ "$1" = -v ] && [ "$2" = xdg-mime ]; then return 1; fi; builtin command "$@"; }\n')
    home = Path(env['HOME'])
    zen_profile(home)
    before = snapshot(home)
    result = inspect('zen-browser', env, BASH_ENV=str(bash_env))
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'WOULD set default browser' not in result.stdout
    assert Path(env['CHECK_LOG']).read_text().count('gio mime ') == 7
    assert_read_only(env, before)
