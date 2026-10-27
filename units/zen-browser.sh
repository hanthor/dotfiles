#!/usr/bin/env bash
# Zen Browser desktop integration and policy. Firefox Accounts is a separate unit.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${UNITS_CHECK:-0}" = 1 ]; then export PYTHONDONTWRITEBYTECODE=1; fi

if skipped_by_profile skip_zen_browser; then
  note "SKIPPED: skip_zen_browser or vm-test"
  finish
fi

# Unlike is_desktop, do not mistake a missing or broken inventory reader for a
# non-desktop host. Explicit host and environment overrides take precedence.
desktop_status() {
  local value="${DOTFILES_IS_DESKTOP:-}"
  [ -n "$value" ] || value="$(host_var is_desktop)"
  case "$value" in
    1|true) return 0 ;;
    0|false) return 1 ;;
  esac
  if ! command -v yq >/dev/null 2>&1; then
    note "FAIL: yq is required to determine desktop inventory membership" >&2
    return 2
  fi
  value="$(yq ".all.children.desktop.hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml")" || return 2
  case "$value" in true) return 0 ;; false) return 1 ;; *)
    note "FAIL: could not determine desktop inventory membership" >&2; return 2 ;;
  esac
}
desktop_status
status=$?
if [ "$status" = 1 ]; then
  note "SKIPPED: not a desktop"
  finish
elif [ "$status" != 0 ]; then
  step "desktop inventory" false
  finish
fi

assets="$DOTFILES_DIR/units/zen-browser"
zen_base="$HOME/.var/app/app.zen_browser.zen/.zen"
flatpak_policy=/var/lib/flatpak/app/app.zen_browser.zen/current/active/files/zen/distribution/policies.json
check_mode="${UNITS_CHECK:-0}"

update_dock() {
  local runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$runtime/bus}" \
  XDG_RUNTIME_DIR="$runtime" python3 - <<'PY'
import ast
import os
import subprocess
import sys
if os.environ.get('UNITS_CHECK') == '1':
    sys.excepthook = lambda kind, value, traceback: print('Zen dock inspection failed (' + kind.__name__ + ')', file=sys.stderr)

get = subprocess.run(['gsettings', 'get', 'org.gnome.shell', 'favorite-apps'],
                     capture_output=True, text=True, check=True)
value = get.stdout.strip()
if os.environ.get('UNITS_CHECK') == '1':
    if value.startswith('@as '):
        value = value[4:]
    if not value:
        raise ValueError('empty dock state')
apps = ast.literal_eval(value) if value else []
if os.environ.get('UNITS_CHECK') == '1' and (not isinstance(apps, list) or not all(isinstance(app, str) for app in apps)):
    raise ValueError('invalid dock state')
new = [app for app in apps if app not in {
    'org.mozilla.firefox.desktop', 'org.mozilla.Thunderbird.desktop'}]
if 'app.zen_browser.zen.desktop' not in new:
    new.insert(0, 'app.zen_browser.zen.desktop')
if os.environ.get('UNITS_CHECK') == '1':
    print('WOULD update GNOME dock' if new != apps else 'OK GNOME dock')
elif new != apps:
    subprocess.run(['gsettings', 'set', 'org.gnome.shell', 'favorite-apps', repr(new)], check=True)
PY
}
if [ "$check_mode" = 1 ]; then
  if [[ "${DBUS_SESSION_BUS_ADDRESS:-}" = autolaunch:* ]]; then
    step "inspect GNOME dock (session bus unavailable)" false
  else
    step "inspect GNOME dock" update_dock
  fi
else
  soft "GNOME dock" update_dock
fi

set_defaults() {
  local mime rc=0
  for mime in x-scheme-handler/http x-scheme-handler/https x-scheme-handler/ftp text/html text/xml application/xhtml+xml application/xml; do
    if command -v xdg-mime >/dev/null 2>&1; then
      xdg-mime default app.zen_browser.zen.desktop "$mime" || rc=1
    else
      gio mime "$mime" app.zen_browser.zen.desktop || rc=1
    fi
  done
  return "$rc"
}
check_defaults() {
  local mime current rc=0
  for mime in x-scheme-handler/http x-scheme-handler/https x-scheme-handler/ftp text/html text/xml application/xhtml+xml application/xml; do
    if command -v xdg-mime >/dev/null 2>&1; then
      current="$(xdg-mime query default "$mime")" || { rc=1; continue; }
    elif command -v gio >/dev/null 2>&1; then
      current="$(LC_ALL=C gio mime "$mime")" || { rc=1; continue; }
      current="${current%%$'\n'*}"
      case "$current" in
        'Default application for '*) current="${current#*: }" ;;
        'No default applications for '*) current='' ;;
        *) rc=1; continue ;;
      esac
    else
      rc=1; continue
    fi
    if [ "$current" != app.zen_browser.zen.desktop ]; then
      note "WOULD set default browser for $mime"
    fi
  done
  return "$rc"
}
if [ "$check_mode" = 1 ]; then
  inspect_path() {
    python3 - "$1" "$2" <<'PY'
import os
import stat
import sys
try:
    info = os.stat(sys.argv[1])
except FileNotFoundError:
    print('absent')
except OSError:
    print('Zen path inspection failed', file=sys.stderr)
    sys.exit(1)
else:
    print('present' if sys.argv[2] == 'exists' or stat.S_ISDIR(info.st_mode) else 'absent')
PY
  }
  if app_present="$(inspect_path "$HOME/.var/app/app.zen_browser.zen" directory)"; then
    if [ "$app_present" = present ]; then step "inspect default browser" check_defaults; fi
  else
    step "inspect Zen installation" false
  fi
  if ! profile_present="$(inspect_path "$zen_base/profiles.ini" exists)"; then
    step "inspect Zen profiles.ini" false
    finish
  fi
else
  if [ -d "$HOME/.var/app/app.zen_browser.zen" ]; then soft "default browser" set_defaults; fi
  if [ -e "$zen_base/profiles.ini" ]; then profile_present=present; else profile_present=absent; fi
fi
if [ "$profile_present" = absent ]; then
  note "SKIPPED: Zen profiles.ini not found"
  finish
fi

profile_path() {
  python3 - "$zen_base" <<'PY'
import configparser
import os
import sys
if os.environ.get('UNITS_CHECK') == '1':
    sys.excepthook = lambda kind, value, traceback: print('Zen profile inspection failed (' + kind.__name__ + ')', file=sys.stderr)

base = sys.argv[1]
config = configparser.ConfigParser()
with open(os.path.join(base, 'profiles.ini'), encoding='utf-8') as f:
    config.read_file(f)
profile = config['Profile0']
path = profile['Path']
if profile.get('IsRelative', '1') == '1':
    path = os.path.join(base, path)
if not os.path.isdir(path):
    raise SystemExit('Zen Profile0 directory does not exist: ' + path)
print(path)
PY
}

install_preferences() {
  local profile
  profile="$(profile_path)" || return 1
  python3 - "$assets/user.js" "$profile/user.js" <<'PY'
import os
from pathlib import Path
import sys
import tempfile
if os.environ.get('UNITS_CHECK') == '1':
    sys.excepthook = lambda kind, value, traceback: print('Zen preferences inspection failed (' + kind.__name__ + ')', file=sys.stderr)

source, dest = map(Path, sys.argv[1:])
managed = source.read_text(encoding='utf-8')
if os.environ.get('UNITS_CHECK') == '1':
    try:
        info = dest.stat()
    except FileNotFoundError:
        info = None
    exists = info is not None
else:
    exists = dest.exists()
old = dest.read_text(encoding='utf-8') if exists else ''
begin = '// BEGIN dotfiles Zen preferences\n'
end = '// END dotfiles Zen preferences\n'
if old == managed:
    new = old  # Existing installations from the Ansible role.
elif begin in old or end in old:
    if old.count(begin) != 1 or old.count(end) != 1 or old.index(begin) > old.index(end):
        raise SystemExit('Invalid managed Zen preferences markers in ' + str(dest))
    before, remainder = old.split(begin, 1)
    _, after = remainder.split(end, 1)
    new = before + begin + managed.rstrip('\n') + '\n' + end + after
else:
    separator = '' if not old or old.endswith('\n') else '\n'
    new = old + separator + begin + managed.rstrip('\n') + '\n' + end
if os.environ.get('UNITS_CHECK') == '1':
    if new != old or info is None or info.st_mode & 0o7777 != 0o644:
        print('WOULD update Zen profile preferences')
    else:
        print('OK Zen profile preferences')
    raise SystemExit(0)
if new != old or not dest.exists():
    fd, temp = tempfile.mkstemp(dir=dest.parent, prefix='.user.js.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(new)
        os.chmod(temp, 0o644)
        os.replace(temp, dest)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
else:
    os.chmod(dest, 0o644)
PY
}
step "Zen profile preferences" install_preferences

# Merge managed policies into each existing file, preserving unrelated local
# policy settings and extension installs. Render before invoking sudo.
render_policy() {
  python3 - "$1" "$assets/policies.json" "$2" <<'PY'
import json
from pathlib import Path
import os
import sys
if os.environ.get('UNITS_CHECK') == '1':
    sys.excepthook = lambda kind, value, traceback: print('Zen policy inspection failed (' + kind.__name__ + ')', file=sys.stderr)

existing, managed, output = map(Path, sys.argv[1:])
with managed.open(encoding='utf-8') as f:
    required = json.load(f)
if os.environ.get('UNITS_CHECK') == '1':
    try:
        info = existing.stat()
    except FileNotFoundError:
        info = None
    exists = info is not None
else:
    exists = existing.exists()
if exists:
    with existing.open(encoding='utf-8') as f:
        current = json.load(f)
else:
    current = {}

def merge(old, new):
    if isinstance(old, dict) and isinstance(new, dict):
        result = old.copy()
        for key, value in new.items():
            result[key] = merge(result[key], value) if key in result else value
        return result
    if isinstance(old, list) and isinstance(new, list):
        return old + [value for value in new if value not in old]
    if isinstance(new, (dict, list)):
        raise ValueError('Existing Zen policy has an incompatible structure')
    return new

if not isinstance(current, dict):
    raise SystemExit('Existing policy must be a JSON object: ' + str(existing))
rendered = json.dumps(merge(current, required), indent=2, ensure_ascii=False) + '\n'
if os.environ.get('UNITS_CHECK') == '1':
    old = existing.read_text(encoding='utf-8') if exists else None
    system = output == Path('system')
    changed = (old != rendered or info is None or info.st_mode & 0o7777 != 0o644
               or (system and (info.st_uid != 0 or info.st_gid != 0)))
    print(('WOULD update ' if changed else 'OK ') + ('Flatpak Zen policy' if system else 'user Zen policy'))
else:
    output.write_text(rendered, encoding='utf-8')
PY
}
install_system_policy() {
  if [ "$check_mode" = 1 ]; then render_policy "$flatpak_policy" system; return $?; fi
  local tmp rc=0
  tmp="$(mktemp)" || return 1
  if render_policy "$flatpak_policy" "$tmp"; then
    if [ "$(id -u)" = 0 ]; then
      install -d -m 0755 -o root -g root "$(dirname "$flatpak_policy")" &&
        { { cmp -s "$tmp" "$flatpak_policy" && [ "$(stat -c '%a:%u:%g' "$flatpak_policy")" = '644:0:0' ]; } || install -m 0644 -o root -g root "$tmp" "$flatpak_policy"; } || rc=1
    else
      sudo -n install -d -m 0755 -o root -g root "$(dirname "$flatpak_policy")" &&
        { { cmp -s "$tmp" "$flatpak_policy" && [ "$(stat -c '%a:%u:%g' "$flatpak_policy")" = '644:0:0' ]; } || sudo -n install -m 0644 -o root -g root "$tmp" "$flatpak_policy"; } || rc=1
    fi
  else
    rc=1
  fi
  rm -f "$tmp"
  return "$rc"
}
install_user_policy() {
  if [ "$check_mode" = 1 ]; then render_policy "$HOME/.zen/distribution/policies.json" user; return $?; fi
  local dest="$HOME/.zen/distribution/policies.json" tmp rc=0
  tmp="$(mktemp)" || return 1
  render_policy "$dest" "$tmp" && install -d -m 0755 "$(dirname "$dest")" && install_if_changed "$tmp" "$dest" 0644 || rc=1
  rm -f "$tmp"
  return "$rc"
}
step "Flatpak Zen policy" install_system_policy
step "user Zen policy" install_user_policy
finish
