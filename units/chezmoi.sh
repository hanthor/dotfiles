#!/usr/bin/env bash
# chezmoi unit: apply the file-based dotfiles from home/ (shell, git, neovim, atuin config).
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

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

is_desktop=0
if command -v yq >/dev/null 2>&1; then
  [ "$(yq ".all.children.desktop.hosts | has(\"$MACHINE\")" "$DOTFILES_DIR/inventory.yml" 2>/dev/null)" = true ] && is_desktop=1
else
  note "warn: yq missing, assuming non-desktop"
fi
export DOTFILES_MACHINE="$MACHINE" DOTFILES_IS_DESKTOP="$is_desktop"

step "chezmoi apply" chezmoi --source "$DOTFILES_DIR" --keep-going --force --no-tty apply --init
finish
