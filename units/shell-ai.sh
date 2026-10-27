#!/usr/bin/env bash
# shell-ai unit: per-host API secrets from Bitwarden -> ~/.config/shell/secrets.sh and fish conf.d.
# Not a chezmoi template: `bitwarden` aborts a whole template on one missing item, while this
# unit writes whatever secrets exist and leaves the files alone when the vault is locked.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

s="$(bw_session)"
if [ -z "$s" ]; then
  note "SKIPPED: vault locked or --no-secrets; secret files left untouched"
  exit 0
fi

trim() { printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }
shq() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
bwget() { BW_SESSION="$s" bw get "$@" 2>/dev/null; }

deepseek="$(trim "$(bwget password deepseek-api-key)")"
forgejo="$(trim "$(bwget notes forgejo | grep 'API Token:' | sed 's/API Token: //')")"
tavily="$(trim "$(bwget password tavily-api-key)")"
meta="$(trim "$(bwget notes meta-api-key)")"
kiro="$(trim "$(bwget notes kiro-api-key)")"

if [ -z "$deepseek$forgejo$tavily$meta$kiro" ]; then
  note "warn: no secrets found in Bitwarden (deepseek-api-key missing?); files left untouched"
  exit 0
fi

# write_atomic dest: stdin -> temp file in the same directory (mode 0600) -> mv
write_atomic() {
  local dest="$1" tmp
  mkdir -p "$(dirname "$dest")" || return 1
  tmp="$(umask 077; mktemp "$dest.XXXXXX")" || return 1
  if cat > "$tmp" && chmod 600 "$tmp" && mv -f "$tmp" "$dest"; then return 0; fi
  rm -f "$tmp"; return 1
}

secrets_sh() {
  echo '# Managed by dotfiles playbook — DO NOT EDIT'
  echo 'export OMP_KIRO_CONFIG="$HOME/.config/omp/kiro.json"'
  [ -z "$deepseek" ] || echo "export DEEPSEEK_API_KEY=$(shq "$deepseek")"
  [ -z "$forgejo" ] || echo "export FORGEJO_TOKEN=$(shq "$forgejo")"
  [ -z "$tavily" ] || echo "export TAVILY_API_KEY=$(shq "$tavily")"
  [ -z "$meta" ] || echo "export META_API_KEY=$(shq "$meta")"
  [ -z "$kiro" ] || echo "export KIRO_API_KEY=$(shq "$kiro")"
}

secrets_fish() {
  echo '# Managed by dotfiles playbook — DO NOT EDIT'
  [ -z "$deepseek" ] || echo "set -gx DEEPSEEK_API_KEY $(shq "$deepseek")"
  [ -z "$forgejo" ] || echo "set -gx FORGEJO_TOKEN $(shq "$forgejo")"
  [ -z "$tavily" ] || echo "set -gx TAVILY_API_KEY $(shq "$tavily")"
  [ -z "$meta" ] || echo "set -gx META_API_KEY $(shq "$meta")"
  [ -z "$kiro" ] || echo "set -gx KIRO_API_KEY $(shq "$kiro")"
  cat <<'FISH'
if command -v bw >/dev/null 2>&1; and test -r /tmp/bw_session
  set -gx KIRO_API_KEY (env BW_SESSION=(cat /tmp/bw_session) bw get item 2706eda5-e8ad-43df-9838-b4e00167e95d 2>/dev/null | jq -r .notes)
  test "$KIRO_API_KEY" = null; and set -e KIRO_API_KEY
end
FISH
}

write_sh() { secrets_sh | write_atomic "$HOME/.config/shell/secrets.sh"; }
write_fish() { secrets_fish | write_atomic "$HOME/.config/fish/conf.d/secrets.fish"; }

step "shell secrets file" write_sh
step "fish secrets file" write_fish
finish
