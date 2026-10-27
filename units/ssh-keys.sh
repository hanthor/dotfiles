#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
export DOTFILES_DIR DOTFILES_MACHINE="$MACHINE"
[ "${UNITS_CHECK:-0}" != 1 ] || export PYTHONDONTWRITEBYTECODE=1
step "SSH key management" python3 "$DOTFILES_DIR/units/ssh-fleet.py" keys
finish
