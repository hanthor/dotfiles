#!/usr/bin/env bash
# chezmoi unit: apply the file-based dotfiles from home/ (shell, git, neovim, atuin config).
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if ! command -v chezmoi >/dev/null 2>&1 && [ "$IS_TERMUX" = 1 ]; then
  soft "pkg install chezmoi" pkg install -y chezmoi
fi
if ! command -v chezmoi >/dev/null 2>&1; then
  note "SKIPPED: chezmoi not installed (run: just packages)"
  exit 0
fi

command -v yq >/dev/null 2>&1 || note "warn: yq missing, assuming non-desktop"
if is_desktop; then desktop=1; else desktop=0; fi
export DOTFILES_MACHINE="$MACHINE" DOTFILES_IS_DESKTOP="$desktop"

step "chezmoi apply" chezmoi --source "$DOTFILES_DIR" --keep-going --force --no-tty apply --init
finish
