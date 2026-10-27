#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=units/package-config.bash
. "$DOTFILES_DIR/units/package-config.bash"

if skipped_by_profile skip_flatpak; then
  note 'SKIPPED: Flatpak disabled for this host/profile'
  exit 0
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if ! package_require_yq >/dev/null 2>&1 || ! package_desktop >/dev/null 2>&1; then
    echo 'Cannot inspect Flatpak desktop configuration' >&2; exit 1
  fi
else
  step 'Flatpak configuration dependencies' package_require_yq
  [ "$UNIT_FAILED" = 0 ] || finish
  step 'desktop classification' package_desktop
  [ "$UNIT_FAILED" = 0 ] || finish
fi
if [ "$PACKAGE_DESKTOP" != 1 ]; then
  note 'SKIPPED: Flatpak is only configured on desktops'
  exit 0
fi

# Shared package list and system remote configuration.
flatpak_vars="$DOTFILES_DIR/units/flatpak-packages.yml"
load_config() {
  local kind
  package_list system_flatpaks "$flatpak_vars" || return 1
  apps=("${PACKAGE_LIST[@]}")
  kind="$(yq -r '.flatpak_remotes | tag' "$flatpak_vars")" || return 1
  [ "$kind" = '!!seq' ] || { echo "$flatpak_vars: flatpak_remotes must be a list" >&2; return 1; }
  remotes="$(yq -r '.flatpak_remotes[] | .name + "\t" + .url' "$flatpak_vars")" || return 1
  local name url
  while IFS=$'\t' read -r name url; do
    [ -n "$name$url" ] || continue
    case "$name" in ''|*[!a-zA-Z0-9_.-]*) echo 'Invalid Flatpak remote name' >&2; return 1 ;; esac
    case "$url" in http://*|https://*) ;; *) echo 'Invalid Flatpak remote URL' >&2; return 1 ;; esac
    case "$url" in *[[:space:]]*) echo 'Invalid Flatpak remote URL' >&2; return 1 ;; esac
  done <<< "$remotes"
}
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if ! load_config >/dev/null 2>&1; then echo 'Cannot inspect Flatpak configuration' >&2; exit 1; fi
else
  step 'Flatpak configuration' load_config
  [ "$UNIT_FAILED" = 0 ] || finish
fi

fix_store() {
  if [ -L /var/lib/flatpak ] && [ ! -e /var/lib/flatpak ]; then
    package_as_root rm /var/lib/flatpak && package_as_root mkdir -p /var/lib/flatpak
  fi
}
add_remotes() {
  local name url rc=0
  while IFS=$'\t' read -r name url; do
    [ -n "$name" ] || continue
    package_as_root flatpak remote-add --if-not-exists --system "$name" "$url" || rc=1
  done <<< "$remotes"
  return "$rc"
}
get_installed() {
  installed="$(package_as_root flatpak list --system --columns=application --app)"
}
remove_unwanted() {
  local pkg remove=()
  for pkg in org.mozilla.firefox org.mozilla.Thunderbird; do
    if printf '%s\n' "$installed" | grep -Fxq "$pkg"; then remove+=("$pkg"); fi
  done
  [ "${#remove[@]}" = 0 ] || package_as_root flatpak uninstall --system -y "${remove[@]}"
}
install_missing() {
  local app missing=() rc=0
  for app in "${apps[@]}"; do
    if ! printf '%s\n' "$installed" | grep -Fxq "$app"; then missing+=("$app"); fi
  done
  [ "${#missing[@]}" -gt 0 ] || return 0
  if package_as_root flatpak install --system -y flathub "${missing[@]}"; then return 0; fi
  for app in "${missing[@]}"; do
    package_as_root flatpak install --system -y flathub "$app" || rc=1
  done
  return "$rc"
}

# Host-specific user installs are independent of the system-wide role lists.
load_user_config() {
  local host="$DOTFILES_DIR/host_vars/$MACHINE.yml" kind name url remote app
  user_remotes=''; user_apps=''
  [ -f "$host" ] || return 0
  kind="$(yq -r '.user_flatpak_remotes | tag' "$host")" || return 1
  case "$kind" in
    '!!null') ;;
    '!!seq') user_remotes="$(yq -r '.user_flatpak_remotes[] | (.name // "") + "\t" + (.url // "")' "$host")" || return 1 ;;
    *) echo "$host: user_flatpak_remotes must be a list" >&2; return 1 ;;
  esac
  [ -z "$user_remotes" ] || while IFS=$'\t' read -r name url; do
    case "$name" in ''|-*|*[!a-zA-Z0-9_.-]*) echo 'Invalid user Flatpak remote name' >&2; return 1 ;; esac
    case "$url" in http://*|https://*) ;; *) echo 'Invalid user Flatpak remote URL' >&2; return 1 ;; esac
    case "$url" in *[[:space:]]*) echo 'Invalid user Flatpak remote URL' >&2; return 1 ;; esac
  done <<< "$user_remotes"
  kind="$(yq -r '.user_flatpaks | tag' "$host")" || return 1
  case "$kind" in
    '!!null') ;;
    '!!seq') user_apps="$(yq -r '.user_flatpaks[] | (.remote // "") + "\t" + (.id // "")' "$host")" || return 1 ;;
    *) echo "$host: user_flatpaks must be a list" >&2; return 1 ;;
  esac
  [ -z "$user_apps" ] || while IFS=$'\t' read -r remote app; do
    case "$remote" in ''|-*|*[!a-zA-Z0-9_.-]*) echo 'Invalid user Flatpak app remote' >&2; return 1 ;; esac
    case "$app" in ''|-*|*[!a-zA-Z0-9_.-]*) echo 'Invalid user Flatpak app ID' >&2; return 1 ;; esac
  done <<< "$user_apps"
}
add_user_remotes() {
  local name url rc=0
  while IFS=$'\t' read -r name url; do
    [ -n "$name" ] || continue
    flatpak remote-add --if-not-exists --user "$name" "$url" || rc=1
  done <<< "$user_remotes"
  return "$rc"
}
install_user_apps() {
  local installed remote app origin rc=0
  installed="$(flatpak list --user --columns=application --app)" || return 1
  while IFS=$'\t' read -r remote app; do
    [ -n "$remote" ] || continue
    if printf '%s\n' "$installed" | grep -Fxq "$app"; then
      if ! origin="$(flatpak info --user --show-origin "$app")"; then
        echo "Could not determine origin of user Flatpak $app" >&2
        rc=1
      elif [ "$origin" != "$remote" ]; then
        note "PRESERVED: user Flatpak $app uses $origin, not requested $remote"
      fi
    elif flatpak install --user -y "$remote" "$app"; then
      installed+=$'\n'"$app"
    else
      rc=1
    fi
  done <<< "$user_apps"
  return "$rc"
}
install_wrappers() {
  local tmp name rc=0
  tmp="$(mktemp)" || return 1
  printf '#!/usr/bin/env bash\nexec flatpak run org.chromium.Chromium "$@"\n' > "$tmp" || { rm -f "$tmp"; return 1; }
  for name in google-chrome google-chrome-stable chromium-browser chromium; do
    install_if_changed "$tmp" "$HOME/.local/bin/$name" 0755 || rc=1
  done
  rm -f "$tmp"
  return "$rc"
}

# Flatpak's ostensibly read-only commands can initialise or update an OSTree
# repository. Confine inspection to a read-only mount and isolated network and
# bus namespaces; never invoke sudo or fall back to an unconfined query.
check_flatpak_query() {
  local env_args=() key
  for key in XDG_DATA_HOME FLATPAK_USER_DIR FLATPAK_SYSTEM_DIR FLATPAK_CONFIG_DIR FLATPAK_DATA_DIR; do
    [ -z "${!key:-}" ] || env_args+=(--setenv "$key" "${!key}")
  done
  bwrap --unshare-all --new-session --die-with-parent --ro-bind / / \
    --proc /proc --dev /dev --tmpfs /run --clearenv \
    --setenv HOME "$HOME" --setenv PATH "$PATH" "${env_args[@]}" \
    --setenv XDG_RUNTIME_DIR /run --setenv XDG_CACHE_HOME /run/cache \
    --setenv DBUS_SYSTEM_BUS_ADDRESS unix:path=/run/no-bus \
    --setenv DBUS_SESSION_BUS_ADDRESS unix:path=/run/no-bus \
    flatpak "$@" </dev/null 2>&1
}

check_flatpak_list() {
  local line
  CHECK_LIST="$(check_flatpak_query "$@")" || return 1
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    case "$line" in *[!a-zA-Z0-9_.-]*) return 1 ;; esac
  done <<< "$CHECK_LIST"
}

check_wrappers() {
  local name path mode rc
  for name in google-chrome google-chrome-stable chromium-browser chromium; do
    path="$HOME/.local/bin/$name"
    if [ ! -e "$path" ] && [ ! -L "$path" ]; then
      note "CHANGE: install Chromium wrapper $name"
    elif [ ! -f "$path" ] || [ ! -r "$path" ]; then
      echo "Cannot inspect Chromium wrapper $name" >&2; UNIT_FAILED=1
    else
      cmp -s "$path" <(printf '#!/usr/bin/env bash\nexec flatpak run org.chromium.Chromium "$@"\n'); rc=$?
      if [ "$rc" = 1 ]; then note "CHANGE: update Chromium wrapper $name"; fi
      if [ "$rc" -gt 1 ]; then echo "Cannot compare Chromium wrapper $name" >&2; UNIT_FAILED=1; continue; fi
      mode="$(stat -L -c %a "$path" 2>/dev/null || stat -L -f %Lp "$path" 2>/dev/null)" || {
        echo "Cannot inspect Chromium wrapper permissions: $name" >&2; UNIT_FAILED=1; continue;
      }
      [ "$mode" = 755 ] || note "CHANGE: set Chromium wrapper $name mode to 0755"
    fi
  done
}

check_flatpak() {
  local system_remotes system_apps user_remote_names user_installed name url app remote origin
  local -A planned_user_origins=()
  check_wrappers
  if [ -L /var/lib/flatpak ] && [ ! -e /var/lib/flatpak ]; then
    note 'CHANGE: repair dangling Flatpak system store'
  fi
  if ! command -v flatpak >/dev/null 2>&1; then
    echo 'Cannot inspect Flatpak: executable unavailable' >&2; UNIT_FAILED=1; return
  fi
  if ! command -v bwrap >/dev/null 2>&1; then
    echo 'Cannot inspect Flatpak safely: bubblewrap is required' >&2; UNIT_FAILED=1; return
  fi
  for name in HOME XDG_DATA_HOME FLATPAK_USER_DIR FLATPAK_SYSTEM_DIR FLATPAK_CONFIG_DIR FLATPAK_DATA_DIR; do
    case "${!name:-}" in /run|/run/*|/var/run|/var/run/*)
      echo 'Cannot inspect Flatpak paths hidden by the sandbox' >&2; UNIT_FAILED=1; return ;;
    esac
  done
  if check_flatpak_list remotes --system --columns=name; then
    system_remotes="$CHECK_LIST"
    while IFS=$'\t' read -r name url; do
      [ -n "$name" ] || continue
      if ! printf '%s\n' "$system_remotes" | grep -Fxq -- "$name"; then
        note "CHANGE: add system Flatpak remote $name"
      fi
    done <<< "$remotes"
  else
    echo 'Cannot inspect system Flatpak remotes in the read-only sandbox' >&2; UNIT_FAILED=1
  fi
  if check_flatpak_list list --system --columns=application --app; then
    system_apps="$CHECK_LIST"
    for app in org.mozilla.firefox org.mozilla.Thunderbird; do
      if printf '%s\n' "$system_apps" | grep -Fxq -- "$app"; then note "CHANGE: remove system Flatpak $app"; fi
    done
    for app in "${apps[@]}"; do
      if ! printf '%s\n' "$system_apps" | grep -Fxq -- "$app"; then note "CHANGE: install system Flatpak $app from flathub"; fi
    done
  else
    echo 'Cannot inspect system Flatpak applications in the read-only sandbox' >&2; UNIT_FAILED=1
  fi
  if ! load_user_config >/dev/null 2>&1; then
    echo 'Cannot inspect user Flatpak configuration' >&2; UNIT_FAILED=1; return
  fi
  if [ -n "$user_remotes" ]; then
    if check_flatpak_list remotes --user --columns=name; then
      user_remote_names="$CHECK_LIST"
      while IFS=$'\t' read -r name url; do
        [ -n "$name" ] || continue
        if ! printf '%s\n' "$user_remote_names" | grep -Fxq -- "$name"; then note "CHANGE: add user Flatpak remote $name"; fi
      done <<< "$user_remotes"
    else
      echo 'Cannot inspect user Flatpak remotes in the read-only sandbox' >&2; UNIT_FAILED=1
    fi
  fi
  if [ -n "$user_apps" ]; then
    if check_flatpak_list list --user --columns=application --app; then
      user_installed="$CHECK_LIST"
      while IFS=$'\t' read -r remote app; do
        [ -n "$remote" ] || continue
        if printf '%s\n' "$user_installed" | grep -Fxq -- "$app"; then
          if [ -n "${planned_user_origins[$app]:-}" ]; then
            origin="${planned_user_origins[$app]}"
            [ "$origin" = "$remote" ] || note "PRESERVED: user Flatpak $app would use $origin, not requested $remote"
          elif check_flatpak_list info --user --show-origin "$app" && [ -n "$CHECK_LIST" ] && [[ "$CHECK_LIST" != *$'\n'* ]]; then
            origin="$CHECK_LIST"
            [ "$origin" = "$remote" ] || note "PRESERVED: user Flatpak $app uses $origin, not requested $remote"
          else
            echo "Cannot inspect origin of user Flatpak $app" >&2; UNIT_FAILED=1
          fi
        else
          note "CHANGE: install user Flatpak $app from $remote"
          planned_user_origins[$app]="$remote"
          user_installed+=$'\n'"$app"
        fi
      done <<< "$user_apps"
    else
      echo 'Cannot inspect user Flatpak applications in the read-only sandbox' >&2; UNIT_FAILED=1
    fi
  fi
  case "${DOTFILES_UPGRADE:-0}" in 1|true) note 'PLANNED: Flatpak system update requested; available updates not inspected offline' ;; esac
}

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  check_flatpak
  finish
fi

if command -v flatpak >/dev/null 2>&1; then
  step 'Flatpak system store' fix_store
  step 'Flatpak remotes' add_remotes
  if get_installed; then
    step 'unwanted system Flatpaks' remove_unwanted
    step 'system Flatpak applications' install_missing
  else
    step 'list system Flatpaks' false
  fi
  case "${DOTFILES_UPGRADE:-0}" in 1|true) soft 'Flatpak update' package_as_root flatpak update --system -y ;; esac
  if load_user_config; then
    [ -z "$user_remotes" ] || step 'user Flatpak remotes' add_user_remotes
    [ -z "$user_apps" ] || step 'user Flatpak applications' install_user_apps
  else
    step 'user Flatpak configuration' false
  fi
else
  note 'flatpak is required for desktop applications' >&2
  step 'Flatpak executable unavailable' false
fi
step 'Chromium Flatpak wrappers' install_wrappers
finish
