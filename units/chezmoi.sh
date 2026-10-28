#!/usr/bin/env bash
# chezmoi unit: apply the file-based dotfiles from home/ (shell, git, neovim, atuin config).
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
# shellcheck source=units/package-config.bash
. "$(dirname "${BASH_SOURCE[0]}")/package-config.bash"

# Tag-only Atuin applies must not overwrite unrelated dotfiles or run hooks.
scope_args=()
case "${DOTFILES_CHEZMOI_SCOPE:-}" in
  '') ;;
  atuin) scope_args=(--exclude=scripts --parent-dirs --recursive=false "$HOME/.config/atuin/config.toml") ;;
  *) note "FAIL: invalid chezmoi scope"; exit 1 ;;
esac

resolve_desktop() {
  local hint="${DOTFILES_IS_DESKTOP:-$(host_var is_desktop)}"
  case "$hint" in
    1|true) desktop=1 ;;
    0|false) desktop=0 ;;
    '')
      package_require_yq && package_desktop || return 1
      desktop="$PACKAGE_DESKTOP"
      ;;
    *) echo 'Invalid desktop classification' >&2; return 1 ;;
  esac
}

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if ! command -v chezmoi >/dev/null 2>&1; then
    note "FAIL: chezmoi not installed; cannot inspect managed files"
    exit 1
  fi
  if ! resolve_desktop; then
    note "FAIL: cannot inspect desktop membership"
    exit 1
  fi
  export DOTFILES_MACHINE="$MACHINE" DOTFILES_IS_DESKTOP="$desktop"
  # Supply the same data as .chezmoi.toml.tmpl without --init: older chezmoi
  # versions write even during a dry-run init. The config is a pipe, not a file.
  machine_json="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$MACHINE")" || {
    note "FAIL: python3 required to encode chezmoi configuration"
    exit 1
  }
  if [ "$desktop" = 1 ]; then desktop_toml=true; else desktop_toml=false; fi
  if ! chezmoi --source "$DOTFILES_DIR" \
      --config <(printf '[data]\nmachine = %s\nis_desktop = %s\n' "$machine_json" "$desktop_toml") --config-format toml \
      --persistent-state "${XDG_CONFIG_HOME:-$HOME/.config}/chezmoi/chezmoistate.boltdb" \
      --dry-run --force --no-tty --no-pager status "${scope_args[@]}" </dev/null; then
    note "FAIL: chezmoi status inspection failed"
    exit 1
  fi
  exit 0
fi

if ! command -v chezmoi >/dev/null 2>&1 && [ "$IS_TERMUX" = 1 ]; then
  soft "pkg install chezmoi" pkg install -y chezmoi
fi
if ! command -v chezmoi >/dev/null 2>&1; then
  if [ "$IS_TERMUX" = 1 ]; then
    note "FAIL: chezmoi not installed; run: pkg install chezmoi"
  elif [ "$IS_MUSL" = 1 ]; then
    note "FAIL: chezmoi not installed; on Alpine/postmarketOS enable the community repository and run: sudo apk add chezmoi"
  else
    note "FAIL: chezmoi not installed; run: just packages"
  fi
  exit 1
fi

if ! resolve_desktop; then
  note "FAIL: cannot determine desktop membership; chezmoi apply skipped"
  exit 1
fi
export DOTFILES_MACHINE="$MACHINE" DOTFILES_IS_DESKTOP="$desktop"

step "chezmoi apply" chezmoi --source "$DOTFILES_DIR" --keep-going --force --no-tty apply --init "${scope_args[@]}"
finish
