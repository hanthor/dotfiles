# shellcheck shell=bash
# Query a direct hosts group without requiring yq on an unbootstrapped phone.
# The fallback accepts the repository's block-style inventory, and fails closed
# for a missing group or an unrecognised hosts entry rather than guessing.
platform_group_contains() {
  local group="$1" line in_children=0 in_group=0 in_hosts=0 group_seen=0 hosts_seen=0 found=1
  if type -P yq >/dev/null 2>&1; then
    local answer
    answer="$(GROUP="$group" MACHINE="$MACHINE" yq -r '.all.children[strenv(GROUP)].hosts | has(strenv(MACHINE))' "$DOTFILES_DIR/inventory.yml")" || return 2
    case "$answer" in true) return 0 ;; false) return 1 ;; *) return 2 ;; esac
  fi
  [ -r "$DOTFILES_DIR/inventory.yml" ] || return 2
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    if [[ "$line" =~ ^'  '[^[:space:]] ]]; then
      in_children=0; in_group=0; in_hosts=0
      [ "$line" = '  children:' ] && in_children=1
      continue
    fi
    [ "$in_children" = 1 ] || continue
    if [[ "$line" =~ ^'    '[^[:space:]] ]]; then
      in_group=0; in_hosts=0
      if [ "$line" = "    $group:" ]; then in_group=1; group_seen=1; fi
      continue
    fi
    [ "$in_group" = 1 ] || continue
    if [[ "$line" =~ ^'      '[^[:space:]] ]]; then
      in_hosts=0
      if [ "$line" = '      hosts:' ]; then in_hosts=1; hosts_seen=1; fi
      continue
    fi
    [ "$in_hosts" = 1 ] || continue
    if [[ "$line" =~ ^'        '([^[:space:]:]+):[[:space:]]*(#.*)?$ ]]; then
      [ "${BASH_REMATCH[1]}" != "$MACHINE" ] || found=0
    elif [[ "$line" =~ ^'        '[^[:space:]] ]]; then
      return 2
    fi
  done < "$DOTFILES_DIR/inventory.yml"
  [ "$group_seen" = 1 ] && [ "$hosts_seen" = 1 ] || return 2
  return "$found"
}

platform_desktop() {
  local value="${DOTFILES_IS_DESKTOP:-}"
  [ -n "$value" ] || value="$(host_var is_desktop)"
  case "$value" in 1|true) return 0 ;; 0|false) return 1 ;; '') platform_group_contains desktop ;; *) return 2 ;; esac
}

platform_root() {
  if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi
}
