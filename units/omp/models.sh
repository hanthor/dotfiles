#!/usr/bin/env bash
# Install only the shared model definition; safe without vault access or package changes.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../lib.sh"

models_merge() {
  local models_cfg="$HOME/.omp/agent/models.yml"
  mkdir -p "$(dirname "$models_cfg")" || return 1
  if [ ! -f "$models_cfg" ] && [ -f "$HOME/.omp/agent/models.yaml" ]; then
    models_cfg="$HOME/.omp/agent/models.yaml"
  fi
  if [ ! -f "$models_cfg" ] && [ -f "$HOME/.omp/agent/models.json" ]; then
    yq -P '.' "$HOME/.omp/agent/models.json" | write_atomic "$models_cfg" || return 1
  fi
  [ -f "$models_cfg" ] || : > "$models_cfg" || return 1
  yq -i ". *= (load(\"$DOTFILES_DIR/units/omp/models.yml\") | explode(.) | ... comments=\"\")" "$models_cfg" || return 1
  chmod 600 "$models_cfg"
}

models_enable() {
  local cfg="$HOME/.omp/agent/config.yml"
  [ -f "$cfg" ] || return 0
  local count
  count="$(yq '(.enabledModels // []) | length' "$cfg")" || return 1
  [ "$count" -gt 0 ] || return 0
  if [ "$(yq '.enabledModels | contains(["lemonade/*"])' "$cfg")" != true ]; then
    yq -i '.enabledModels += ["lemonade/*"]' "$cfg" || return 1
  fi
  chmod 600 "$cfg"
}

step "models merged" models_merge
step "model filter updated" models_enable
finish
