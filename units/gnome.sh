#!/usr/bin/env bash
# GNOME desktop configuration; session commands run as the invoking desktop user.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${UNITS_CHECK:-0}" = 1 ]; then export PYTHONDONTWRITEBYTECODE=1; fi

if skipped_by_profile skip_gnome; then
  note "SKIPPED: skip_gnome or vm-test"
  finish
fi

# Unlike is_desktop(), distinguish a missing/broken inventory reader from a
# negative result: silently skipping a desktop would leave it unconfigured.
desktop="${DOTFILES_IS_DESKTOP:-$(host_var is_desktop)}"
case "$desktop" in
  1|true) ;;
  0|false) note "SKIPPED: not a desktop"; finish ;;
  '')
    if ! command -v yq >/dev/null 2>&1 || ! desktop="$(yq ".all.children.desktop.hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml")"; then
      step "determine desktop membership (yq required)" false
      finish
    fi
    case "$desktop" in
      true) ;;
      false) note "SKIPPED: not a desktop"; finish ;;
      *) step "determine desktop membership (invalid inventory result)" false; finish ;;
    esac
    ;;
  *) step "determine desktop membership (invalid override)" false; finish ;;
esac

# Do not let GLib autolaunch a throwaway D-Bus session when run over SSH.
# An existing runtime bus belongs to the invoking user and is safe to use.
if [ -z "${XDG_RUNTIME_DIR:-}" ] && [ -S "/run/user/$UID/bus" ]; then
  export XDG_RUNTIME_DIR="/run/user/$UID"
fi
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [ -n "${XDG_RUNTIME_DIR:-}" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
session_ok=0
if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && [[ "$DBUS_SESSION_BUS_ADDRESS" != autolaunch:* ]] && gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus --method org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1; then
  session_ok=1
else
  note "GNOME user D-Bus session unavailable; session settings require a reachable user bus and gdbus"
fi
require_session() { [ "$session_ok" = 1 ]; }

assets="$DOTFILES_DIR/units/gnome"
dconf_dir="$HOME/.config/dconf"
keybindings="$dconf_dir/gnome-keybindings.ini"
pending="$dconf_dir/.gnome-keybindings.pending"

install_keybindings() {
  mkdir -p "$dconf_dir" && chmod 0755 "$dconf_dir" || return 1
  if ! cmp -s "$assets/gnome-keybindings.ini" "$keybindings" || [ "$(stat -c %a "$keybindings" 2>/dev/null)" != 644 ]; then
    # Keep the notification until the live user's dconf load succeeds.
    : > "$pending" || return 1
  fi
  install_if_changed "$assets/gnome-keybindings.ini" "$keybindings" 0644
}
load_keybindings() {
  require_session && dconf load /org/gnome/settings-daemon/plugins/media-keys/ < "$keybindings" && rm -f "$pending"
}
if [ "${UNITS_CHECK:-0}" != 1 ]; then
  if install_keybindings; then
    note "ok    GNOME keybindings file"
    if [ -f "$pending" ]; then
      step "load GNOME keybindings in user session" load_keybindings
    fi
  else
    step "GNOME keybindings file" false
  fi
fi

# Values come from the same inventory variables as the former role, not a
# second hard-coded list. Host variables override group variables.
brew_prefix=""
extensions_value=""
read_configuration() {
  local host_file="$DOTFILES_DIR/host_vars/$MACHINE.yml" host_extensions="null"
  command -v yq >/dev/null 2>&1 || { echo "yq is required to read GNOME configuration" >&2; return 1; }
  brew_prefix="$(host_var brew_prefix)"
  if [ -z "$brew_prefix" ]; then
    brew_prefix="$(yq -r '.brew_prefix' "$DOTFILES_DIR/group_vars/all.yml")" || return 1
  fi
  [ -n "$brew_prefix" ] && [ "$brew_prefix" != null ] || return 1
  if [ -f "$host_file" ]; then
    host_extensions="$(yq -o=json -I=0 '.gnome_enabled_extensions' "$host_file")" || return 1
  fi
  if [ "$host_extensions" != null ]; then
    extensions_value="$host_extensions"
  else
    extensions_value="$(yq -o=json -I=0 '.gnome_enabled_extensions' "$DOTFILES_DIR/group_vars/all.yml")" || return 1
  fi
  case "$extensions_value" in \[*\]) ;; *) echo "gnome_enabled_extensions must be a list" >&2; return 1 ;; esac
}
config_ok=0
if read_configuration; then
  config_ok=1
  note "ok    read GNOME configuration"
else
  step "read GNOME configuration" false
fi

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  check_gnome_files() {
    python3 - "$assets" "$HOME" "$DOTFILES_DIR/units/gnome-avatar.py" <<'PY'
import importlib.util
import grp
from pathlib import Path
import pwd
import stat
import sys
sys.excepthook = lambda kind, value, traceback: print('GNOME file inspection failed (' + kind.__name__ + ')', file=sys.stderr)

assets, home, avatar_script = map(Path, sys.argv[1:])
def directory(path, label):
    try:
        info = path.stat()
        changed = not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o7777 != 0o755
    except FileNotFoundError:
        changed = True
    if changed:
        print('WOULD create or fix ' + label)
def file(path, data, mode, label):
    try:
        info = path.stat()
        changed = not stat.S_ISREG(info.st_mode) or path.read_bytes() != data or info.st_mode & 0o7777 != mode
    except FileNotFoundError:
        changed = True
    if changed:
        print('WOULD update ' + label)
    return changed

dconf = home / '.config/dconf'
directory(dconf, 'dconf directory')
changed = file(dconf / 'gnome-keybindings.ini', (assets / 'gnome-keybindings.ini').read_bytes(), 0o644, 'GNOME keybindings file')
if changed or (dconf / '.gnome-keybindings.pending').is_file():
    print('WOULD load GNOME keybindings in user session')
extensions = home / '.local/share/gnome-shell/extensions'
directory(extensions, 'GNOME extensions directory')
for uuid in ('copyous@boerdereinar.dev', 'papershell@lalovene.github.com', 'paperwm@paperwm.github.com'):
    source, target = assets / 'extensions' / uuid, extensions / uuid
    if not source.is_dir():
        raise FileNotFoundError('missing extension assets: ' + uuid)
    directory(target, 'extension ' + uuid)
    for path in source.rglob('*'):
        dest = target / path.relative_to(source)
        label = 'extension ' + uuid + '/' + str(path.relative_to(source))
        if path.is_dir():
            directory(dest, label)
        elif path.is_file():
            file(dest, path.read_bytes(), 0o644, label)
        else:
            raise ValueError('unsupported extension asset: ' + str(path))

# The image is downloaded during apply, so its contents cannot be compared offline.
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('gnome_avatar', avatar_script)
avatar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(avatar)
try:
    account = avatar.ACCOUNT.read_text()
except FileNotFoundError:
    account = ''
file(avatar.ACCOUNT, avatar.account_with_icon(account).encode(), 0o644, 'AccountsService account')
try:
    info = avatar.ICON.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o7777 != 0o644:
        print('WOULD update AccountsService avatar')
except FileNotFoundError:
    print('WOULD install AccountsService avatar')
try:
    gdm = pwd.getpwnam('gdm')
except KeyError:
    pass
else:
    gid = grp.getgrnam('gdm').gr_gid
    try:
        info = (avatar.GDM_CACHE / 'james').stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o7777 != 0o644 or (info.st_uid, info.st_gid) != (gdm.pw_uid, gid):
            print('WOULD update GDM avatar metadata')
    except FileNotFoundError:
        print('WOULD install GDM avatar')
    print('PLAN refresh GDM avatar; remote image not inspected')
print('PLAN refresh AccountsService avatar; remote image not inspected')
PY
  }
  check_gnome_session() {
    require_session || return 1
    python3 - "$assets" "$brew_prefix" "$extensions_value" "$config_ok" <<'PY'
import ast
import configparser
import io
import json
from pathlib import Path
import subprocess
import sys
sys.excepthook = lambda kind, value, traceback: print('GNOME session inspection failed (' + kind.__name__ + ')', file=sys.stderr)

assets, prefix = Path(sys.argv[1]), sys.argv[2]
config_ok = sys.argv[4] == '1'
desired_extensions = json.loads(sys.argv[3]) if config_ok else None
def command(*args):
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=True).stdout.strip()
def settings(schema, key):
    return command('gsettings', 'get', schema, key)
def ini(text):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_file(io.StringIO(text))
    return parser

def ptyxis():
    uuid = ast.literal_eval(settings('org.gnome.Ptyxis', 'default-profile-uuid'))
    current_cmd = ast.literal_eval(settings('org.gnome.Ptyxis.Profile:/org/gnome/ptyxis/profiles/' + uuid + '/', 'custom-command'))
    font = ast.literal_eval(settings('org.gnome.Ptyxis', 'font-name'))
    if current_cmd != prefix + '/bin/fish' or font != 'JetBrainsMono Nerd Font 12':
        print('WOULD configure Ptyxis profile')

def extension_settings():
    desired = ini((assets / 'gnome-extensions-dconf.dump').read_text())
    actual = ini(command('dconf', 'dump', '/org/gnome/shell/extensions/'))
    if any(not actual.has_option(section, key) or actual.get(section, key) != value
           for section in desired.sections() for key, value in desired.items(section)):
        print('WOULD load GNOME extension settings')

def enabled_extensions():
    value = settings('org.gnome.shell', 'enabled-extensions')
    if value.startswith('@as '):
        value = value[4:]
    if ast.literal_eval(value) != desired_extensions:
        print('WOULD update enabled GNOME extensions')

def rdp():
    if 'Status: enabled' not in command('grdctl', 'rdp', 'status'):
        print('WOULD enable GNOME RDP protocol')

def touchpad():
    if settings('org.gnome.desktop.peripherals.touchpad', 'tap-to-click') != 'false':
        print('WOULD disable touchpad tap-to-click')

def remote_service():
    state = command('systemctl', '--user', 'show', '--property=LoadState', '--property=UnitFileState',
                    '--property=ActiveState', 'gnome-remote-desktop.service')
    properties = dict(line.split('=', 1) for line in state.splitlines() if '=' in line)
    if not all(key in properties for key in ('LoadState', 'UnitFileState', 'ActiveState')):
        raise ValueError('incomplete systemd service state')
    if (properties['LoadState'], properties['UnitFileState'], properties['ActiveState']) != ('loaded', 'enabled', 'active'):
        print('WOULD enable and start GNOME Remote Desktop user service')

failed = False
checks = [('extension settings', extension_settings), ('RDP', rdp), ('remote service', remote_service), ('touchpad', touchpad)]
if config_ok:
    checks.extend((('Ptyxis profile', ptyxis), ('enabled extensions', enabled_extensions)))
for label, inspect in checks:
    try:
        inspect()
    except Exception as error:
        print('FAIL inspect ' + label + ' (' + type(error).__name__ + ')', file=sys.stderr)
        failed = True
if failed:
    sys.exit(1)
PY
  }
  step "inspect GNOME files" check_gnome_files
  step "inspect GNOME user session" check_gnome_session
  finish
fi
disable_tap_to_click() {
  require_session || return 1
  [ "$(gsettings get org.gnome.desktop.peripherals.touchpad tap-to-click)" = false ] ||
    gsettings set org.gnome.desktop.peripherals.touchpad tap-to-click false
}
soft "disable touchpad tap-to-click" disable_tap_to_click


configure_ptyxis() {
  local uuid current_cmd current_font
  require_session || return 1
  uuid="$(gsettings get org.gnome.Ptyxis default-profile-uuid)" || return 1
  uuid="${uuid//\'/}"
  current_cmd="$(gsettings get "org.gnome.Ptyxis.Profile:/org/gnome/ptyxis/profiles/${uuid}/" custom-command 2>/dev/null)" || current_cmd=""
  current_font="$(gsettings get org.gnome.Ptyxis font-name 2>/dev/null)" || current_font=""
  current_cmd="${current_cmd//\'/}"; current_font="${current_font//\'/}"
  if [ "$current_cmd" != "$brew_prefix/bin/fish" ] || [ "$current_font" != 'JetBrainsMono Nerd Font 12' ]; then
    gsettings set "org.gnome.Ptyxis.Profile:/org/gnome/ptyxis/profiles/${uuid}/" use-custom-command true &&
      gsettings set "org.gnome.Ptyxis.Profile:/org/gnome/ptyxis/profiles/${uuid}/" custom-command "$brew_prefix/bin/fish" &&
      gsettings set org.gnome.Ptyxis use-system-font false &&
      gsettings set org.gnome.Ptyxis font-name 'JetBrainsMono Nerd Font 12'
  fi
}
if [ "$config_ok" = 1 ]; then soft "Ptyxis profile" configure_ptyxis; fi

install_avatar() {
  local tmp rc=0
  tmp="$(mktemp -d)" || return 1
  if curl -fsSL https://reilly.asia/profile.png -o "$tmp/profile.png"; then
    if [ "$EUID" = 0 ]; then
      python3 "$DOTFILES_DIR/units/gnome-avatar.py" "$tmp/profile.png" || rc=1
    else
      sudo -n python3 "$DOTFILES_DIR/units/gnome-avatar.py" "$tmp/profile.png" || rc=1
    fi
  else
    rc=1
  fi
  rm -rf "$tmp"
  return "$rc"
}
step "AccountsService avatar" install_avatar

deploy_extensions() {
  local uuid src dest file rel
  local -a entries
  mkdir -p "$HOME/.local/share/gnome-shell/extensions" && chmod 0755 "$HOME/.local/share/gnome-shell/extensions" || return 1
  shopt -s globstar dotglob nullglob
  for uuid in copyous@boerdereinar.dev papershell@lalovene.github.com paperwm@paperwm.github.com; do
    src="$assets/extensions/$uuid"
    dest="$HOME/.local/share/gnome-shell/extensions/$uuid"
    [ -d "$src" ] || { echo "missing extension assets: $src" >&2; return 1; }
    mkdir -p "$dest" && chmod 0755 "$dest" || return 1
    entries=("$src"/**)
    for file in "${entries[@]}"; do
      rel="${file#"$src"/}"
      if [ -d "$file" ]; then
        mkdir -p "$dest/$rel" && chmod 0755 "$dest/$rel" || return 1
      elif [ -f "$file" ]; then
        install_if_changed "$file" "$dest/$rel" 0644 || return 1
      else
        echo "unsupported extension asset: $file" >&2
        return 1
      fi
    done
  done
}
step "deploy user GNOME extensions" deploy_extensions
load_extension_settings() {
  require_session && dconf load /org/gnome/shell/extensions/ < "$assets/gnome-extensions-dconf.dump"
}
soft "load GNOME extension settings in user session" load_extension_settings
if [ "$config_ok" = 1 ]; then
  enable_extensions() { require_session && gsettings set org.gnome.shell enabled-extensions "$extensions_value"; }
  soft "enable GNOME extensions in user session" enable_extensions
fi

enable_rdp() {
  local status
  require_session || return 1
  status="$(grdctl rdp status 2>/dev/null)" || status=""
  case "$status" in *'Status: enabled'*) return 0 ;; esac
  grdctl rdp enable
}
soft "enable GNOME RDP protocol" enable_rdp
enable_remote_service() { require_session && systemctl --user enable --now gnome-remote-desktop.service; }
soft "enable GNOME Remote Desktop user service" enable_remote_service
finish
