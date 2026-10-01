#!/usr/bin/env bash
# Shared helper: find-or-create-or-update a Bitwarden item by exact name.
#
# Usage:
#   bw_upsert_item <name> <item_json>
#
# <item_json> must be a complete Bitwarden item object (as produced by
# `bw get template item` + jq, or hand-built) including the desired "name"
# field. Looks up an existing item with that exact name via `bw list items
# --search`, then edits it in place if found, or creates it otherwise.
#
# Requires BW_SESSION to already be exported (see bw-unlock.sh / bw-resolve.sh).
# Requires: bw, jq.
#
# This is a function library, not a standalone script — source it:
#   source "$(dirname "$0")/bw-item.sh"

bw_find_item_id() {
  local name="$1" type_filter="${2:-}"
  bw list items --search "$name" 2>/dev/null \
    | jq -r --arg name "$name" --arg type "$type_filter" '
        .[] | select(.name == $name)
            | select($type == "" or (.type|tostring) == $type)
            | .id
      ' \
    | head -n1
}

bw_upsert_item() {
  local name="$1" item_json="$2" type_filter="${3:-}"
  local existing_id
  existing_id=$(bw_find_item_id "$name" "$type_filter")

  if [ -n "$existing_id" ]; then
    echo "  → updating existing Bitwarden item '$name' (id: $existing_id)..." >&2
    echo "$item_json" | bw encode | bw edit item "$existing_id" >/dev/null
    echo "  ✓ updated." >&2
  else
    echo "  → creating new Bitwarden item '$name'..." >&2
    echo "$item_json" | bw encode | bw create item >/dev/null
    echo "  ✓ created." >&2
  fi
}
