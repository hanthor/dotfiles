#!/usr/bin/env bash
# shell-ai unit: per-host API secrets from Bitwarden -> ~/.config/shell/secrets.sh and fish conf.d.
# Not a chezmoi template: `bitwarden` aborts a whole template on one missing item, while this
# unit writes whatever secrets exist and leaves the files alone when the vault is locked.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  if [ "${UNITS_NO_SECRETS:-0}" = 1 ]; then
    note "SKIPPED: secrets disabled; secret files left untouched"
    exit 0
  fi
  for path in "$HOME/.config/shell/secrets.sh" "$HOME/.config/fish/conf.d/secrets.fish"; do
    if [ -L "$path" ] || [ ! -e "$path" ]; then
      note "PARTIAL: $path absent or symlinked; apply would replace it if secrets are available"
    elif [ ! -f "$path" ] || ! mode="$(stat -c '%a' "$path")"; then
      note "FAIL  cannot inspect $path"
    elif [ "$mode" != 600 ]; then
      note "PARTIAL: $path mode differs from 0600; apply would replace it if secrets are available"
    else
      note "ok    $path mode 0600"
    fi
  done
  note "FAIL  cannot compare shell secrets safely: Bitwarden item reads may persist audit events"
  exit 1
fi


s="$(bw_session)"
if [ -z "$s" ]; then
  note "SKIPPED: vault locked or --no-secrets; secret files left untouched"
  exit 0
fi

trim() { printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'; }
shq() { printf "'%s'" "${1//\'/\'\\\'\'}"; }
fishq() { local value="${1//\\/\\\\}"; printf "'%s'" "${value//\'/\\\'}"; }
bwget() { BW_SESSION="$s" bw get "$@" 2>/dev/null; }

deepseek="$(bwget password deepseek-api-key)" || deepseek=""
forgejo="$(bwget notes forgejo)" || forgejo=""
tavily="$(bwget password tavily-api-key)" || tavily=""
meta="$(bwget notes meta-api-key)" || meta=""
kiro="$(bwget notes kiro-api-key)" || kiro=""
deepseek="$(trim "$deepseek")"
forgejo="$(trim "$(printf '%s\n' "$forgejo" | grep 'API Token:' | sed 's/API Token: //')")"
tavily="$(trim "$tavily")"
meta="$(trim "$meta")"
kiro="$(trim "$kiro")"

if [ -z "$deepseek$forgejo$tavily$meta$kiro" ]; then
  note "warn: no secrets found in Bitwarden (deepseek-api-key missing?); files left untouched"
  exit 0
fi

secrets_sh() {
  echo '# Managed by dotfiles playbook — DO NOT EDIT'
  echo 'export OMP_KIRO_CONFIG="$HOME/.config/omp/kiro.json"'
  [ -z "$deepseek" ] || printf 'export DEEPSEEK_API_KEY=%s\n' "$(shq "$deepseek")"
  [ -z "$forgejo" ] || printf 'export FORGEJO_TOKEN=%s\n' "$(shq "$forgejo")"
  [ -z "$tavily" ] || printf 'export TAVILY_API_KEY=%s\n' "$(shq "$tavily")"
  [ -z "$meta" ] || printf 'export META_API_KEY=%s\n' "$(shq "$meta")"
  [ -z "$kiro" ] || printf 'export KIRO_API_KEY=%s\n' "$(shq "$kiro")"
}

secrets_fish() {
  echo '# Managed by dotfiles playbook — DO NOT EDIT'
  [ -z "$deepseek" ] || printf 'set -gx DEEPSEEK_API_KEY %s\n' "$(fishq "$deepseek")"
  [ -z "$forgejo" ] || printf 'set -gx FORGEJO_TOKEN %s\n' "$(fishq "$forgejo")"
  [ -z "$tavily" ] || printf 'set -gx TAVILY_API_KEY %s\n' "$(fishq "$tavily")"
  [ -z "$meta" ] || printf 'set -gx META_API_KEY %s\n' "$(fishq "$meta")"
  [ -z "$kiro" ] || printf 'set -gx KIRO_API_KEY %s\n' "$(fishq "$kiro")"
  cat <<'FISH'
if command -v bw >/dev/null 2>&1; and command -v jq >/dev/null 2>&1; and test -r /tmp/bw_session
  begin
    set -lx BW_SESSION (cat /tmp/bw_session)
    if set -l kiro_item (bw get item 2706eda5-e8ad-43df-9838-b4e00167e95d 2>/dev/null | string collect; test $pipestatus[1] -eq 0)
      if set -l kiro_key (printf '%s' "$kiro_item" | jq -er '.notes | select(type == "string" and length > 0)' 2>/dev/null | string collect; test $pipestatus[2] -eq 0)
        set -gx KIRO_API_KEY "$kiro_key"
      end
    end
  end
end
FISH
}


write_sh() { secrets_sh | write_atomic "$HOME/.config/shell/secrets.sh"; }
write_fish() { secrets_fish | write_atomic "$HOME/.config/fish/conf.d/secrets.fish"; }

step "shell secrets file" write_sh
step "fish secrets file" write_fish
finish
