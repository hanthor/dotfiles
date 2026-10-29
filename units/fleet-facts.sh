#!/usr/bin/env bash
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if [ "$MACHINE" = matrix ] || [ "$MACHINE" = telengana ]; then
  note "SKIPPED: fleet facts excluded on retired VPS"
  finish
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  step "check fleet facts publication" env PYTHONDONTWRITEBYTECODE=1 python3 "$DOTFILES_DIR/units/fleet-facts.py" "$DOTFILES_DIR" "$MACHINE" "$IS_TERMUX" --check
  finish
fi
step "collect and publish fleet facts" python3 "$DOTFILES_DIR/units/fleet-facts.py" "$DOTFILES_DIR" "$MACHINE" "$IS_TERMUX"
finish
