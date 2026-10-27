#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "$0")/lib.sh"
# shellcheck source=units/package-config.bash
. "$DOTFILES_DIR/units/package-config.bash"

if [ "$IS_TERMUX" = 1 ] || [ "$IS_MUSL" = 1 ]; then
  note 'SKIPPED: Homebrew requires glibc; use Termux packages or apk on this host'
  exit 0
fi

brew_prefix="${BREW_PREFIX:-/home/linuxbrew/.linuxbrew}"
brew_bin="$brew_prefix/bin/brew"
PATH="$brew_prefix/bin:$PATH"
export PATH HOMEBREW_NO_AUTO_UPDATE=1 HOMEBREW_NO_ENV_HINTS=1

load_config() {
  package_require_yq && package_desktop || return 1
  package_list core_taps || return 1; core_taps=("${PACKAGE_LIST[@]}")
  package_list core_brews || return 1; core_brews=("${PACKAGE_LIST[@]}")
  package_list core_tap_brews || return 1; core_tap_brews=("${PACKAGE_LIST[@]}")
  package_list desktop_taps || return 1; desktop_taps=("${PACKAGE_LIST[@]}")
  package_list desktop_brews || return 1; desktop_brews=("${PACKAGE_LIST[@]}")
  package_list extra_brews || return 1; extra_brews=("${PACKAGE_LIST[@]}")
  package_list desktop_casks || return 1; desktop_casks=("${PACKAGE_LIST[@]}")
  package_list desktop_vscode_extensions || return 1; extensions=("${PACKAGE_LIST[@]}")
  package_list brew_blocked || return 1; blocked=("${PACKAGE_LIST[@]}")

  local pkg banned
  for pkg in "${core_brews[@]}" "${core_tap_brews[@]}" "${desktop_brews[@]}" "${extra_brews[@]}" "${desktop_casks[@]}"; do
    for banned in "${blocked[@]}"; do
      if [ "${pkg##*/}" = "$banned" ]; then
        echo "$pkg is in brew_blocked; remove it from the install lists" >&2
        return 1
      fi
    done
  done
}

fix_owner() {
  local parent="${brew_prefix%/.linuxbrew}" owner
  [ -d "$parent" ] || return 0
  owner="$(stat -c %u "$parent" 2>/dev/null || stat -f %u "$parent")" || return 1
  [ "$owner" = "$(id -u)" ] || package_as_root chown -R "$(id -un)" "$parent"
}

install_compiler() {
  if command -v cc >/dev/null 2>&1 && command -v gcc >/dev/null 2>&1; then return 0; fi
  local ID='' ID_LIKE=''
  [ -r /etc/os-release ] || { echo 'cc and gcc are required for Homebrew; install a compiler toolchain' >&2; return 1; }
  # shellcheck source=/dev/null
  . /etc/os-release
  case " $ID $ID_LIKE " in
    *' debian '*|*' ubuntu '*) package_as_root apt-get update && package_as_root apt-get install -y build-essential ;;
    *) echo 'cc and gcc are required for Homebrew; install a compiler toolchain' >&2; return 1 ;;
  esac
}

install_brew() {
  [ -x "$brew_bin" ] && return 0
  local script rc
  command -v curl >/dev/null 2>&1 || { echo 'curl is required to install Homebrew' >&2; return 1; }
  script="$(mktemp)" || return 1
  rc=0
  curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$script" && NONINTERACTIVE=1 /bin/bash "$script" || rc=$?
  rm -f "$script"
  [ "$rc" = 0 ] && [ -x "$brew_bin" ]
}

ensure_yq() {
  if package_require_yq >/dev/null 2>&1; then return 0; fi
  echo 'Installing Mike Farah yq for package configuration'
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0='' "$brew_bin" install yq || {
    echo 'Unable to install yq with Homebrew' >&2
    return 1
  }
  hash -r
  if ! package_require_yq >/dev/null 2>&1; then
    echo 'Mike Farah yq is unavailable after Homebrew installation' >&2
    return 1
  fi
}

render_brewfile() {
  local pkg
    echo '# Core packages'
    for pkg in "${core_taps[@]}"; do printf 'tap "%s"\n' "$pkg"; done
    echo
    for pkg in "${core_brews[@]}"; do printf 'brew "%s"\n' "$pkg"; done
    echo
    for pkg in "${core_tap_brews[@]}"; do printf 'brew "%s"\n' "$pkg"; done
    echo
    if [ "$PACKAGE_DESKTOP" = 1 ]; then
      echo '# Desktop packages'
      for pkg in "${desktop_taps[@]}"; do printf 'tap "%s"\n' "$pkg"; done
      echo
      for pkg in "${desktop_brews[@]}"; do printf 'brew "%s"\n' "$pkg"; done
      echo
      for pkg in "${extra_brews[@]}"; do printf 'brew "%s"\n' "$pkg"; done
      echo
      for pkg in "${desktop_casks[@]}"; do printf 'cask "%s"\n' "$pkg"; done
      echo
      if [ "$(uname -s)" = Darwin ]; then
        for pkg in "${extensions[@]}"; do printf 'vscode "%s"\n' "$pkg"; done
      fi
    fi
}

deploy_brewfile() {
  local tmp
  tmp="$(mktemp "$HOME/.Brewfile.XXXXXX")" || return 1
  render_brewfile > "$tmp" || { rm -f "$tmp"; return 1; }
  install_if_changed "$tmp" "$HOME/Brewfile" 0644
  local rc=$?
  rm -f "$tmp"
  return "$rc"
}

tap_and_trust() {
  local pkg tap seen=' ' rc=0
  for pkg in "${core_taps[@]}" "${desktop_taps[@]}" "${core_brews[@]}" "${core_tap_brews[@]}" "${desktop_brews[@]}" "${extra_brews[@]}" "${desktop_casks[@]}"; do
    case "$pkg" in
      */*/*) tap="${pkg%/*}" ;;
      */*) tap="$pkg" ;;
      *) continue ;;
    esac
    case "$seen" in *" $tap "*) continue ;; esac
    seen="$seen$tap "
    "$brew_bin" tap "$tap" || rc=1
    # Older Homebrew versions may not support trust, as in the Ansible role.
    soft "trust $tap" "$brew_bin" trust "$tap"
  done
  return "$rc"
}

bundle() {
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0='' \
    "$brew_bin" bundle install "--file=$HOME/Brewfile" --no-upgrade
}

uninstall_blocked() {
  local pkg err rc=0
  err="$(mktemp)" || return 1
  for pkg in "${blocked[@]}"; do
    if ! "$brew_bin" uninstall --formula "$pkg" 2>"$err"; then
      if ! grep -Fq 'No such keg' "$err"; then cat "$err" >&2; rc=1; fi
    fi
  done
  rm -f "$err"
  return "$rc"
}

# Homebrew may initialise caches or fetch metadata even for some queries.
# Constrain every Homebrew/Python probe to a read-only, offline namespace.
check_brew_query() {
  bwrap --unshare-all --new-session --die-with-parent --ro-bind / / \
    --proc /proc --dev /dev --tmpfs /run --clearenv \
    --setenv HOME "$HOME" --setenv PATH "$PATH" \
    --setenv XDG_RUNTIME_DIR /run --setenv XDG_CACHE_HOME /run/cache \
    --setenv DBUS_SYSTEM_BUS_ADDRESS unix:path=/run/no-bus \
    --setenv DBUS_SESSION_BUS_ADDRESS unix:path=/run/no-bus \
    --setenv HOMEBREW_CACHE /run/brew-cache --setenv HOMEBREW_LOGS /run/brew-logs \
    --setenv HOMEBREW_TEMP /run --setenv HOMEBREW_NO_AUTO_UPDATE 1 \
    --setenv HOMEBREW_NO_ANALYTICS 1 --setenv HOMEBREW_NO_ENV_HINTS 1 \
    --setenv HOMEBREW_NO_BOOTSNAP 1 \
    --setenv GIT_TERMINAL_PROMPT 0 --setenv NONINTERACTIVE 1 \
    --setenv GIT_CONFIG_COUNT 1 --setenv GIT_CONFIG_KEY_0 credential.helper --setenv GIT_CONFIG_VALUE_0 '' \
    --setenv PYTHONDONTWRITEBYTECODE 1 "$@" 2>&1
}

check_brew() {
  local parent="${brew_prefix%/.linuxbrew}" owner uid rc mode result pkg tap seen=' ' taps line info kind count
  if [ -d "$parent" ]; then
    if owner="$(stat -c %u "$parent" 2>/dev/null || stat -f %u "$parent" 2>/dev/null)" && uid="$(id -u)"; then
      [ "$owner" = "$uid" ] || note 'CHANGE: repair Homebrew directory ownership'
    else
      echo 'Cannot inspect Homebrew directory ownership' >&2; UNIT_FAILED=1
    fi
  fi
  if ! command -v cc >/dev/null 2>&1 || ! command -v gcc >/dev/null 2>&1; then
    note 'CHANGE: Homebrew compiler toolchain is missing'
  fi
  if [ ! -x "$brew_bin" ]; then note 'CHANGE: install Homebrew'; fi
  if ! package_require_yq >/dev/null 2>&1; then
    echo 'Cannot inspect Homebrew configuration: Mike Farah yq is required' >&2
    UNIT_FAILED=1; return
  fi
  if ! load_config >/dev/null 2>&1; then echo 'Cannot inspect Homebrew configuration' >&2; UNIT_FAILED=1; return; fi
  if [ ! -e "$HOME/Brewfile" ] && [ ! -L "$HOME/Brewfile" ]; then
    note 'CHANGE: install Brewfile'
  elif [ ! -f "$HOME/Brewfile" ] || [ ! -r "$HOME/Brewfile" ]; then
    echo 'Cannot inspect Brewfile' >&2; UNIT_FAILED=1
  else
    cmp -s "$HOME/Brewfile" <(render_brewfile); rc=$?
    if [ "$rc" = 1 ]; then note 'CHANGE: update Brewfile'; fi
    if [ "$rc" -gt 1 ]; then echo 'Cannot compare Brewfile' >&2; UNIT_FAILED=1; fi
    if mode="$(stat -L -c %a "$HOME/Brewfile" 2>/dev/null || stat -L -f %Lp "$HOME/Brewfile" 2>/dev/null)"; then
      [ "$mode" = 644 ] || note 'CHANGE: set Brewfile mode to 0644'
    else
      echo 'Cannot inspect Brewfile permissions' >&2; UNIT_FAILED=1
    fi
  fi
  note 'PLANNED: attempt Homebrew tap trust on apply; current trust state not inspected'
  if [ ! -x "$brew_bin" ]; then
    note 'PLANNED: install configured Homebrew taps and packages after bootstrap'
    return
  fi
  if ! command -v bwrap >/dev/null 2>&1; then
    echo 'Cannot inspect Homebrew safely: bubblewrap is required' >&2; UNIT_FAILED=1; return
  fi
  case "$HOME" in /run|/run/*|/var/run|/var/run/*)
    echo 'Cannot inspect Homebrew home hidden by the sandbox' >&2; UNIT_FAILED=1; return ;;
  esac
  if taps="$(check_brew_query "$brew_bin" tap </dev/null)"; then
    for line in $taps; do
      case "$line" in *[!a-zA-Z0-9_./-]*) echo 'Cannot inspect Homebrew taps' >&2; UNIT_FAILED=1; return ;; esac
    done
    for pkg in "${core_taps[@]}" "${desktop_taps[@]}" "${core_brews[@]}" "${core_tap_brews[@]}" "${desktop_brews[@]}" "${extra_brews[@]}" "${desktop_casks[@]}"; do
      case "$pkg" in */*/*) tap="${pkg%/*}" ;; */*) tap="$pkg" ;; *) continue ;; esac
      case "$seen" in *" $tap "*) continue ;; esac
      seen="$seen$tap "
      if ! printf '%s\n' "$taps" | grep -Fxqi -- "$tap"; then note "CHANGE: tap Homebrew repository $tap"; fi
    done
  else
    echo 'Cannot inspect Homebrew taps in the read-only sandbox' >&2; UNIT_FAILED=1
  fi
  if result="$(render_brewfile | check_brew_query "$brew_bin" bundle check --file=- --no-upgrade --verbose)"; then
    note 'ok    Homebrew bundle dependencies'
  else
    # Do not print command output: Homebrew diagnostics can contain credentials.
    # Bundle uses the same nonzero status for drift and inspection failures.
    if [[ "$result" == *"can't satisfy your Brewfile's dependencies"* ]]; then
      note 'CHANGE: Homebrew bundle dependencies need installation'
      for pkg in "${core_taps[@]}" "${core_brews[@]}" "${core_tap_brews[@]}" "${desktop_taps[@]}" "${desktop_brews[@]}" "${extra_brews[@]}" "${desktop_casks[@]}" "${extensions[@]}"; do
        if [[ "$result" == *" $pkg needs to be "* ]]; then note "CHANGE: Homebrew bundle dependency $pkg"; fi
      done
    else
      echo 'Cannot inspect Homebrew bundle dependencies in the read-only sandbox' >&2
    fi
    UNIT_FAILED=1
  fi
  # Resolve each blocked name through Homebrew itself, including aliases and
  # renamed formulae. Unknown/unreadable metadata is an inspection failure,
  # not evidence that the formula is absent.
  for pkg in "${blocked[@]}"; do
    if ! info="$(check_brew_query "$brew_bin" info --json=v1 --formula "$pkg" </dev/null)" ||
       ! count="$(printf '%s' "$info" | yq -p=json -r 'length' 2>/dev/null)" || [ "$count" != 1 ] ||
       ! kind="$(printf '%s' "$info" | yq -p=json -r '.[0].installed | tag' 2>/dev/null)" || [ "$kind" != '!!seq' ] ||
       ! count="$(printf '%s' "$info" | yq -p=json -r '.[0].installed | length' 2>/dev/null)"; then
      echo "Cannot inspect blocked Homebrew formula $pkg in the read-only sandbox" >&2; UNIT_FAILED=1; continue
    fi
    case "$count" in
      ''|*[!0-9]*) echo "Cannot inspect blocked Homebrew formula $pkg" >&2; UNIT_FAILED=1 ;;
      0) ;;
      *) note "CHANGE: uninstall blocked Homebrew formula $pkg" ;;
    esac
  done
  if [ -x "$brew_prefix/bin/python3" ]; then
    check_brew_query "$brew_prefix/bin/python3" -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("packaging") else 42)' </dev/null >/dev/null
    rc=$?
    case "$rc" in
      0) ;;
      42) note 'CHANGE: install Homebrew Python packaging' ;;
      *) echo 'Cannot inspect Homebrew Python packaging in the read-only sandbox' >&2; UNIT_FAILED=1 ;;
    esac
  else
    note 'PLANNED: best-effort Python packaging install if Homebrew Python is available'
  fi
  case "${DOTFILES_UPGRADE:-0}" in 1|true) note 'PLANNED: Homebrew upgrade requested; available upgrades not inspected offline' ;; esac
}

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  check_brew
  finish
fi

step 'Homebrew directory ownership' fix_owner
step 'Homebrew compiler' install_compiler
step 'Homebrew installation' install_brew
if [ ! -x "$brew_bin" ]; then
  step 'Homebrew executable unavailable' false
  finish
fi
if ensure_yq; then
  note 'ok    Homebrew yq bootstrap'
else
  step 'Homebrew yq bootstrap' false
  finish
fi
if load_config; then
  note 'ok    Homebrew configuration'
else
  step 'Homebrew configuration' false
  finish
fi
if deploy_brewfile; then
  note 'ok    Brewfile'
  brewfile_ready=1
else
  step 'Brewfile' false
  brewfile_ready=0
fi
step 'Homebrew taps' tap_and_trust
if [ "$brewfile_ready" = 1 ]; then
  step 'Homebrew bundle' bundle
else
  note 'SKIPPED: Homebrew bundle (Brewfile deployment failed)'
fi
step 'blocked Homebrew packages' uninstall_blocked
case "${DOTFILES_UPGRADE:-0}" in 1|true) soft 'Homebrew upgrade' "$brew_bin" upgrade ;; esac
soft 'brew Python packaging' "$brew_prefix/bin/python3" -m pip install packaging --break-system-packages --quiet
finish
