# shellcheck shell=bash
# Helpers for the package units. The repository YAML remains authoritative.
package_require_yq() {
  local candidate version
  for candidate in "$(type -P yq || :)" "${BREW_PREFIX:-/home/linuxbrew/.linuxbrew}/bin/yq"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] || continue
    if version="$("$candidate" --version 2>/dev/null)" && [[ "$version" == *github.com/mikefarah/yq* ]]; then
      PACKAGE_YQ="$candidate"
      return 0
    fi
  done
  echo 'Mike Farah yq is required to read package and inventory configuration' >&2
  return 1
}

yq() { "$PACKAGE_YQ" "$@"; }

# package_list KEY [FILE]: populate PACKAGE_LIST from a YAML sequence. Group
# defaults are overridden by the host file; FILE selects an authoritative role
# vars file instead (role vars take precedence over group and host vars).
package_list() {
  local key="$1" source="${2:-$DOTFILES_DIR/group_vars/all.yml}" host="$DOTFILES_DIR/host_vars/$MACHINE.yml" has value kind item
  PACKAGE_LIST=()
  if [ "$#" -eq 1 ] && [ -f "$host" ]; then
    has="$(yq -r "has(\"$key\")" "$host")" || return 1
    [ "$has" != true ] || source="$host"
  fi
  kind="$(yq -r ".$key | tag" "$source")" || return 1
  case "$kind" in '!!null') return 0 ;; '!!seq') ;; *) echo "$source: $key must be a list" >&2; return 1 ;; esac
  # Package names and IDs cannot contain whitespace or control characters.
  value="$(yq -r ".$key | .[]" "$source")" || return 1
  [ -n "$value" ] || return 0
  while IFS= read -r item; do
    case "$item" in ''|*[!a-zA-Z0-9_@.+/-]*) echo "$source: invalid value in $key" >&2; return 1 ;; esac
    PACKAGE_LIST+=("$item")
  done <<< "$value"
}

# Resolve desktop membership; malformed or missing inputs fail.
package_desktop() {
  local value="${DOTFILES_IS_DESKTOP:-}" host="$DOTFILES_DIR/host_vars/$MACHINE.yml" has kind
  if [ -z "$value" ] && [ -f "$host" ]; then
    has="$(yq -r 'has("is_desktop")' "$host")" || return 1
    case "$has" in true|false) ;; *) echo 'Invalid host desktop configuration' >&2; return 1 ;; esac
    if [ "$has" = true ]; then value="$(yq -r '.is_desktop' "$host")" || return 1; fi
  fi
  if [ -z "$value" ]; then
    kind="$(yq -r '.all.children.desktop.hosts | tag' "$DOTFILES_DIR/inventory.yml")" || return 1
    [ "$kind" = '!!map' ] || { echo 'Invalid desktop inventory hosts' >&2; return 1; }
    value="$(MACHINE="$MACHINE" yq -r '.all.children.desktop.hosts | has(strenv(MACHINE))' "$DOTFILES_DIR/inventory.yml")" || return 1
  fi
  case "$value" in 1|true) PACKAGE_DESKTOP=1 ;; 0|false) PACKAGE_DESKTOP=0 ;; *) echo 'Invalid desktop classification' >&2; return 1 ;; esac
}

package_as_root() {
  if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi
}
