#!/usr/bin/env bash
# omp unit: install, skills, Kiro plugin, routing, auth-broker client config.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PATH="$HOME/.bun/bin:$HOME/.local/bin:$PATH"
cfg="$HOME/.omp/agent/config.yml"
skills_dest="$HOME/.omp/agent/skills/james"

if [ "$IS_TERMUX" = 1 ]; then
  note "SKIPPED: omp has no Android build"
  exit 0
fi

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  note "FAIL: omp plugin and broker state cannot be inspected safely without invoking omp; its startup side effects are not constrained"
  exit 1
fi

# shellcheck source=units/omp/auth-broker.conf
. "$DOTFILES_DIR/units/omp/auth-broker.conf"

omp_install() {
  if ! command -v omp >/dev/null 2>&1 && [ "$IS_MUSL" = 1 ]; then
    mkdir -p "$HOME/.cache" || return 1
    curl -fsSL https://omp.sh/install -o "$HOME/.cache/omp-install.sh" || return 1
    PI_INSTALL_DIR="$HOME/.local/bin" sh "$HOME/.cache/omp-install.sh" --binary || return 1
    if [ ! -x "$HOME/.bun/bin/bun" ]; then
      curl -fsSL https://bun.sh/install -o "$HOME/.cache/bun-install.sh" || return 1
      bash "$HOME/.cache/bun-install.sh" || return 1
    fi
  fi
  if ! command -v omp >/dev/null 2>&1; then
    echo "omp not installed; run: just packages" >&2
    return 1
  fi
}

skills_sync() {
  local src="$DOTFILES_DIR/roles/pi/files/skills"
  mkdir -p "$skills_dest" || return 1
  if command -v rsync >/dev/null 2>&1; then
    rsync -a "$src/" "$skills_dest/" || return 1
  else
    cp -a "$src/." "$skills_dest/" || return 1
  fi
  find "$skills_dest" -type f \( -name '*.sh' -o -name '*.mjs' \) -exec chmod 755 {} +
}

claude_links() {
  local d rc=0
  mkdir -p "$HOME/.claude/skills" || return 1
  for d in "$skills_dest"/*/; do
    [ -d "$d" ] || continue
    d="${d%/}"
    ln -sfn "$d" "$HOME/.claude/skills/$(basename "$d")" || rc=1
  done
  return $rc
}

kiro_plugin() {
  if omp plugin list --json 2>/dev/null | grep -q omp-kiro-provider; then
    return 0
  fi
  omp plugin install github:elkibalion/omp-kiro-provider
}

ccleft_install() {
  [ -x "$HOME/go/bin/ccleft" ] && return 0
  command -v go >/dev/null 2>&1 || return 0
  go install github.com/tuna-os/ccleft/cmd/ccleft@latest
}

routing_merge() {
  mkdir -p "$(dirname "$cfg")" || return 1
  [ -f "$cfg" ] || : > "$cfg" || return 1
  yq -i ". *= (load(\"$DOTFILES_DIR/units/omp/routing.yml\") | explode(.) | ... comments=\"\")" "$cfg"
}

broker_url() {
  mkdir -p "$(dirname "$cfg")" || return 1
  [ -f "$cfg" ] || : > "$cfg" || return 1
  URL="$OMP_AUTH_BROKER_URL" yq -i '.auth.broker.url = strenv(URL)' "$cfg" || return 1
  chmod 600 "$cfg"
}

broker_token() {
  local s tok
  s="$(bw_session)"
  [ -n "$s" ] || return 0
  tok="$(BW_SESSION="$s" bw get password "$OMP_AUTH_BROKER_BW_ITEM" 2>/dev/null)"
  [ -n "$tok" ] || return 0
  TOKEN="$tok" yq -i '.auth.broker.token = strenv(TOKEN)' "$cfg" || return 1
  chmod 600 "$cfg"
}

broker_status() {
  omp auth-broker status
}

have_omp() { command -v omp >/dev/null 2>&1; }

step "omp installed" omp_install
step "skills synced" skills_sync
step "claude skill links" claude_links
if have_omp; then step "kiro plugin" kiro_plugin; else note "skip  kiro plugin (omp missing)"; fi
soft "ccleft" ccleft_install
step "kiro.json" install_if_changed "$DOTFILES_DIR/units/omp/kiro.json" "$HOME/.config/omp/kiro.json" 0644
step "omp-route" install_if_changed "$DOTFILES_DIR/units/omp/omp-route" "$HOME/.local/bin/omp-route" 0755
step "routing merged" routing_merge
step "broker url" broker_url
step "broker token" broker_token
if [ "$(yq '.auth.broker | has("token")' "$cfg" 2>/dev/null)" != true ]; then
  note "PARTIAL: broker token not written (vault locked or item missing); run: just seed-omp-broker from a client with SSH access to spindle, then just apply-tags omp"
fi
if have_omp; then soft "broker status" broker_status; else note "skip  broker status (omp missing)"; fi
finish
