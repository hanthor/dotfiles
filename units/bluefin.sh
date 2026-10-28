#!/usr/bin/env bash
# Bluefin branding, wallpaper rotation, corral and desktop swappiness.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${UNITS_CHECK:-0}" = 1 ]; then export PYTHONDONTWRITEBYTECODE=1; fi

assets="$DOTFILES_DIR/units/bluefin"
image=ghcr.io/projectbluefin/common:latest

if skipped_by_profile skip_bluefin; then
  note "SKIPPED: bluefin disabled by host/profile"
  finish
fi

# Unlike is_desktop(), distinguish a missing/broken inventory reader from a
# negative membership result. An explicit host override does not need yq.
desktop="${DOTFILES_IS_DESKTOP:-$(host_var is_desktop)}"
case "$desktop" in
  true|1) ;;
  false|0) note "SKIPPED: not a desktop"; finish ;;
  *)
    if ! command -v yq >/dev/null 2>&1; then
      step "desktop inventory requires yq" false
      finish
    fi
    if ! desktop="$(yq ".all.children.desktop.hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml")"; then
      step "desktop inventory lookup" false
      finish
    fi
    case "$desktop" in
      true) ;;
      false) note "SKIPPED: not a desktop"; finish ;;
      *) step "desktop inventory lookup returned an invalid result" false; finish ;;
    esac
    ;;
esac

uid="$(id -u)" || { step "resolve user UID" false; finish; }
bus="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/$uid/bus}"
export DBUS_SESSION_BUS_ADDRESS="$bus"
# Check simple local socket addresses directly; gsettings also probes other
# D-Bus transports and reports failures below.
case "$bus" in
  unix:path=*%*|unix:path=*\;*) ;;
  unix:path=*)
    bus_socket="${bus#unix:path=}"
    bus_socket="${bus_socket%%,*}"
    if [ ! -S "$bus_socket" ]; then note "PARTIAL: session bus socket unavailable ($bus_socket)"; fi
    ;;
esac
is_gnome=0
if { [ "${UNITS_CHECK:-0}" != 1 ] || [[ "$bus" != autolaunch:* ]]; } && gsettings get org.gnome.desktop.interface color-scheme >/dev/null 2>&1; then
  is_gnome=1
else
  note "PARTIAL: GNOME session detection failed; Bluefin branding, fonts and extensions not applied"
fi
is_bluefin=0
if grep -iq Bluefin /etc/os-release; then
  is_bluefin=1
else
  rc=$?
  if [ "$rc" != 1 ]; then step "detect Bluefin OS" false; finish; fi
fi
force_bluefin="$(host_var force_bluefin false)"

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "$is_gnome" != 1 ]; then step "inspect GNOME session" false; fi
  check_bluefin_files() {
    python3 - "$assets" "$HOME" "$bus" <<'PY'
import datetime
from pathlib import Path
import subprocess
import sys
sys.excepthook = lambda kind, value, traceback: print('Bluefin inspection failed (' + kind.__name__ + ')', file=sys.stderr)

assets, home, bus = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

def compare(name, dest, content, mode):
    try:
        info = dest.stat()
        changed = not dest.is_file() or dest.read_bytes() != content or info.st_mode & 0o7777 != mode
    except FileNotFoundError:
        changed = True
    print(('WOULD update ' if changed else 'OK ') + name)

localbin = home / '.local/bin'
try:
    info = localbin.stat()
    print(('OK ' if localbin.is_dir() and info.st_mode & 0o7777 == 0o755 else 'WOULD update ') + 'local bin directory')
except FileNotFoundError:
    print('WOULD create local bin directory')
compare('wallpaper rotation script', localbin / 'bluefin-wallpaper-rotate.py',
        (assets / 'files/bluefin-wallpaper-rotate.py').read_bytes(), 0o755)
corral = localbin / 'corral'
try:
    info = corral.stat()
    if not corral.is_file() or info.st_mode & 0o7777 != 0o755:
        print('WOULD install corral')
    else:
        print('PLAN refresh corral; remote version/checksum not inspected')
except FileNotFoundError:
    print('WOULD install corral')
for path in (localbin / 'tailvm-go', localbin / 'tailvm', home / '.tailvm-completion.bash',
             home / '.tailvm-completion.zsh', home / '.config/fish/completions/tailvm.fish'):
    if path.exists() or path.is_symlink():
        print('WOULD remove retired tailvm file: ' + str(path))
text = (assets / 'templates/bluefin-wallpaper-rotate.service.j2').read_text()
if '\n' in bus or '\r' in bus:
    raise ValueError('invalid session bus address')
bus_value = bus.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
assignment = 'DBUS_SESSION_BUS_ADDRESS=' + bus_value
if any(c.isspace() or c in '\\"' for c in bus):
    assignment = '"' + assignment + '"'
executable = str(home / '.local/bin/bluefin-wallpaper-rotate.py')
if any(ord(c) < 32 or ord(c) == 127 for c in executable):
    raise ValueError('invalid wallpaper executable path')
executable_value = executable.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
if any(c.isspace() or c in '\\"' for c in executable):
    executable_value = '"' + executable_value + '"'
for token, value in (("{{ ansible_facts['env']['HOME'] }}/.local/bin/bluefin-wallpaper-rotate.py", executable_value),
                     ('Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{{ user_uid_cmd.stdout | trim }}/bus',
                      'Environment=' + assignment)):
    if token not in text:
        raise ValueError('missing service template token')
    text = text.replace(token, value)
units = home / '.config/systemd/user'
compare('wallpaper service', units / 'bluefin-wallpaper-rotate.service', text.encode(), 0o644)
compare('wallpaper timer unit', units / 'bluefin-wallpaper-rotate.timer',
        (assets / 'templates/bluefin-wallpaper-rotate.timer.j2').read_bytes(), 0o644)
compare('zRAM swappiness', Path('/etc/sysctl.d/99-zram.conf'),
        b'# Optimize zRAM swappiness for compressed RAM swap\nvm.swappiness = 150\n', 0o644)
wallpaper = home / '.local/share/backgrounds/bluefin' / (datetime.datetime.now().strftime('%m') + '-bluefin.xml')
if not wallpaper.exists():
    wallpaper = Path('/usr/share/backgrounds/bluefin') / wallpaper.name
if wallpaper.exists():
    for key in ('picture-uri', 'picture-uri-dark'):
        result = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.background', key],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=True)
        import ast
        current = ast.literal_eval(result.stdout.strip())
        print(('WOULD rotate ' if current != wallpaper.as_uri() else 'OK ') + key)
else:
    print('SKIPPED wallpaper rotation: current month wallpaper is absent')
PY
  }
  check_timer() {
    local state line load='?' enabled='?' active='?'
    state="$(systemctl --user show --property=LoadState --property=UnitFileState --property=ActiveState bluefin-wallpaper-rotate.timer)" || return 1
    while IFS= read -r line; do
      case "$line" in
        LoadState=*) load="${line#*=}" ;;
        UnitFileState=*) enabled="${line#*=}" ;;
        ActiveState=*) active="${line#*=}" ;;
      esac
    done <<< "$state"
    [ "$load" != '?' ] && [ "$enabled" != '?' ] && [ "$active" != '?' ] || return 1
    if [ "$load" = loaded ] && [ "$enabled" = enabled ] && [ "$active" = active ]; then
      note "OK wallpaper timer"
    else
      note "WOULD enable and start wallpaper timer"
    fi
  }
  check_extensions() {
    local all enabled uuid
    all="$(gnome-extensions list)" || return 1
    enabled="$(gnome-extensions list --enabled)" || return 1
    for uuid in appindicatorsupport@rgcjonas.gmail.com dash-to-dock@micxgx.gmail.com blur-my-shell@aunetx gsconnect@andyholmes.github.io logomenu@aryan_k search-light@icedman.github.com caffeine@patapon.info; do
      if [[ $'\n'"$all"$'\n' != *$'\n'"$uuid"$'\n'* ]]; then
        note "WOULD install GNOME extension $uuid"
      elif [[ $'\n'"$enabled"$'\n' != *$'\n'"$uuid"$'\n'* ]]; then
        note "WOULD enable GNOME extension $uuid"
      fi
    done
  }
  step "inspect Bluefin files and wallpaper" check_bluefin_files
  step "inspect wallpaper timer" check_timer
  if [ "$is_gnome" = 1 ] && { [ "$is_bluefin" = 0 ] || [ "$force_bluefin" = true ] || [ "$force_bluefin" = 1 ]; }; then
    note "PLAN refresh Bluefin branding and fonts; remote image and archives not inspected"
    step "inspect GNOME extensions" check_extensions
  fi
  finish
fi

sync_branding() {
  local tmp container='' rc=0 extracted=0 source target
  tmp="$(mktemp -d)" || return 1
  if podman pull --arch amd64 "$image" && container="$(podman create "$image")" && [ -n "$container" ]; then
    mkdir -p "$tmp/dconf" "$tmp/backgrounds" "$tmp/icons" "$tmp/ublue-os" || rc=1
    if [ "$rc" = 0 ]; then
      while IFS='|' read -r source target; do
        if podman cp "$container:$source" "$tmp/$target"; then
          extracted=$((extracted + 1))
        else
          note "PARTIAL: Bluefin image asset unavailable: $source"
        fi
      done <<'ASSETS'
system_files/bluefin/usr/share/glib-2.0/schemas/zz0-bluefin-modifications.gschema.override|.
system_files/bluefin/etc/dconf/db/distro.d/.|dconf/
system_files/bluefin/usr/share/backgrounds/bluefin/.|backgrounds/
system_files/bluefin/usr/share/icons/hicolor/.|icons/
system_files/bluefin/usr/share/ublue-os/.|ublue-os/
ASSETS
      if [ "$extracted" = 0 ]; then
        echo "No Bluefin image assets could be extracted" >&2
        rc=1
      else
        python3 - "$tmp/backgrounds" "$HOME/.local/share/backgrounds/bluefin" <<'PY' || rc=1
import os
import pathlib
import sys
from xml.sax.saxutils import escape

root = pathlib.Path(sys.argv[1])
old = b'/usr/share/backgrounds/bluefin/'
new = os.fsencode(escape(sys.argv[2] + '/', {'"': '&quot;', "'": '&apos;'}))
for path in root.rglob('*.xml'):
    if path.is_symlink():
        continue
    data = path.read_bytes()
    updated = data.replace(old, new)
    if updated != data:
        path.write_bytes(updated)
PY
        if [ "$rc" = 0 ]; then
          install -d -m 0755 "$HOME/.local/share/backgrounds/bluefin" "$HOME/.local/share/icons/hicolor" "$HOME/.local/share/ublue-os" \
            && cp -a "$tmp/backgrounds/." "$HOME/.local/share/backgrounds/bluefin/" \
            && cp -a "$tmp/icons/." "$HOME/.local/share/icons/hicolor/" \
            && cp -a "$tmp/ublue-os/." "$HOME/.local/share/ublue-os/" || rc=1
        fi
        DBUS_SESSION_BUS_ADDRESS="$bus" python3 "$assets/files/bluefin-sync.py" "$tmp" || rc=1
      fi
    fi
  else
    rc=1
  fi
  if [ -n "$container" ]; then podman rm "$container" || rc=1; fi
  rm -rf "$tmp" || rc=1
  return "$rc"
}

install_bluefin_fonts() {
  local tmp rc=0
  tmp="$(mktemp -d)" || return 1
  install -d -m 0755 "$HOME/.local/share/fonts/Inter" "$HOME/.local/share/fonts/JetBrainsMono" \
    && curl -fsSL --retry 1 https://github.com/rsms/inter/releases/latest/download/Inter-4.1.zip -o "$tmp/Inter.zip" \
    && curl -fsSL --retry 1 https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip -o "$tmp/JetBrainsMono.zip" \
    && unzip -ouq "$tmp/Inter.zip" -d "$HOME/.local/share/fonts/Inter" \
    && unzip -ouq "$tmp/JetBrainsMono.zip" -d "$HOME/.local/share/fonts/JetBrainsMono" || rc=1
  rm -rf "$tmp" || rc=1
  return "$rc"
}

install_corral() {
  local arch name tmp hash file actual expected='' rc=0
  arch="$(uname -m)" || return 1
  case "$arch" in x86_64) arch=amd64 ;; aarch64) arch=arm64 ;; esac
  name="corral-linux-$arch"
  tmp="$(mktemp -d)" || return 1
  if curl -fsSL --retry 1 "https://github.com/hanthor/corral/releases/download/binaries/$name" -o "$tmp/$name" \
    && curl -fsSL --retry 1 https://github.com/hanthor/corral/releases/download/binaries/SHA256SUMS -o "$tmp/SHA256SUMS"; then
    while read -r hash file; do
      file="${file#\*}"
      file="${file#./}"
      if [ "$file" = "$name" ]; then expected="$hash"; break; fi
    done < "$tmp/SHA256SUMS"
    actual="$(sha256sum "$tmp/$name")" || rc=1
    actual="${actual%% *}"
    if [[ ! "$expected" =~ ^[[:xdigit:]]{64}$ ]] || [ "${expected,,}" != "${actual,,}" ]; then
      echo "Corral checksum missing or mismatched for $name" >&2
      rc=1
    elif [ "$rc" = 0 ]; then
      install_if_changed "$tmp/$name" "$HOME/.local/bin/corral" 0755 || rc=1
    fi
  else
    rc=1
  fi
  rm -rf "$tmp" || rc=1
  return "$rc"
}

remove_tailvm() {
  rm -f "$HOME/.local/bin/tailvm-go" "$HOME/.local/bin/tailvm" \
    "$HOME/.tailvm-completion.bash" "$HOME/.tailvm-completion.zsh" \
    "$HOME/.config/fish/completions/tailvm.fish"
}

rotation_units() {
  local tmp service="$HOME/.config/systemd/user/bluefin-wallpaper-rotate.service"
  local timer="$HOME/.config/systemd/user/bluefin-wallpaper-rotate.timer" changed=0 rc=0
  tmp="$(mktemp -d)" || return 1
  python3 - "$assets/templates/bluefin-wallpaper-rotate.service.j2" "$tmp/service" "$HOME" "$bus" <<'PY' || rc=1
import pathlib
import sys

source, destination, home, bus = sys.argv[1:]
text = pathlib.Path(source).read_text()
if '\n' in bus or '\r' in bus:
    raise ValueError('invalid session bus address')
bus_value = bus.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
assignment = 'DBUS_SESSION_BUS_ADDRESS=' + bus_value
if any(c.isspace() or c in '\\"' for c in bus):
    assignment = '"' + assignment + '"'
executable = home + '/.local/bin/bluefin-wallpaper-rotate.py'
if any(ord(c) < 32 or ord(c) == 127 for c in executable):
    raise ValueError('invalid wallpaper executable path')
executable_value = executable.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"')
if any(c.isspace() or c in '\\"' for c in executable):
    executable_value = '"' + executable_value + '"'
for token, value in (("{{ ansible_facts['env']['HOME'] }}/.local/bin/bluefin-wallpaper-rotate.py", executable_value),
                     ('Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{{ user_uid_cmd.stdout | trim }}/bus',
                      'Environment=' + assignment)):
    if token not in text:
        raise ValueError(f'missing service template token: {token}')
    text = text.replace(token, value)
pathlib.Path(destination).write_text(text)
PY
  if [ "$rc" = 0 ]; then
    install -d -m 0755 "$(dirname "$service")" || rc=1
    if ! cmp -s "$tmp/service" "$service" || [ "$(stat -c %a "$service" 2>/dev/null)" != 644 ]; then changed=1; fi
    if ! cmp -s "$assets/templates/bluefin-wallpaper-rotate.timer.j2" "$timer" || [ "$(stat -c %a "$timer" 2>/dev/null)" != 644 ]; then changed=1; fi
    if [ "$rc" = 0 ]; then
      install_if_changed "$tmp/service" "$service" 0644 \
        && install_if_changed "$assets/templates/bluefin-wallpaper-rotate.timer.j2" "$timer" 0644 || rc=1
    fi
    if [ "$rc" = 0 ] && [ "$changed" = 1 ]; then systemctl --user daemon-reload || rc=1; fi
  fi
  rm -rf "$tmp" || rc=1
  return "$rc"
}

root_run() {
  if [ "$EUID" = 0 ]; then "$@"; else sudo -n "$@"; fi
}

zram_swappiness() {
  local tmp dest=/etc/sysctl.d/99-zram.conf rc=0
  tmp="$(mktemp)" || return 1
  printf '# Optimize zRAM swappiness for compressed RAM swap\nvm.swappiness = 150\n' > "$tmp" || rc=1
  if [ "$rc" = 0 ] && { ! cmp -s "$tmp" "$dest" || [ "$(stat -c %a "$dest" 2>/dev/null)" != 644 ]; }; then
    root_run install -m 0644 "$tmp" "$dest" && root_run sysctl -p "$dest" || rc=1
  fi
  rm -f "$tmp" || rc=1
  return "$rc"
}

if [ "$is_gnome" = 1 ] && { [ "$is_bluefin" = 0 ] || [ "$force_bluefin" = true ] || [ "$force_bluefin" = 1 ]; }; then
  step "Bluefin branding and settings" sync_branding
  step "Bluefin fonts" install_bluefin_fonts
  step "font cache" fc-cache -f
fi

step "local bin directory" install -d -m 0755 "$HOME/.local/bin"
step "wallpaper rotation script" install_if_changed "$assets/files/bluefin-wallpaper-rotate.py" "$HOME/.local/bin/bluefin-wallpaper-rotate.py" 0755
step "corral" install_corral
step "remove retired tailvm" remove_tailvm
step "wallpaper systemd units" rotation_units
step "wallpaper timer" systemctl --user enable --now bluefin-wallpaper-rotate.timer
step "rotate wallpaper" env DBUS_SESSION_BUS_ADDRESS="$bus" python3 "$HOME/.local/bin/bluefin-wallpaper-rotate.py"
if [ "$is_gnome" = 1 ] && { [ "$is_bluefin" = 0 ] || [ "$force_bluefin" = true ] || [ "$force_bluefin" = 1 ]; }; then
  soft "GNOME extensions" env DBUS_SESSION_BUS_ADDRESS="$bus" python3 "$assets/files/install-extensions.py"
fi
step "zRAM swappiness" zram_swappiness
finish
