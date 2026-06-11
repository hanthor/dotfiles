#!/bin/sh
# goose-wrapper: translates old hive CLI interface to goose 1.37.0 subcommands,
# and runs goose in a restart loop so that ^C (clear_on_kick) doesn't kill
# the tmux session — only goose-real dies and restarts.
#
# Upstream Go binary calls: goose --model X --prompt "$(cat /tmp/prompt.txt)"
# We rewrite to:          goose-real run -s --model X --text "..."
#
# The shell expands $(cat file) before calling this wrapper, so --prompt's
# argument is the full multiline content as a single shell word.

# Trap SIGINT so that hive's ^C/clear kills only goose-real, not this wrapper.
trap '' INT

# Parse args from the old CLI interface
MODEL=""
TEXT=""
HAD_PROMPT=false

while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --prompt) TEXT="$2"; HAD_PROMPT=true; shift 2 ;;
    *) shift ;;
  esac
done

# Build args array
ARGS="run -s"
[ -n "$MODEL" ] && ARGS="$ARGS --model $MODEL"

if $HAD_PROMPT && [ -n "$TEXT" ]; then
  # First launch with bootstrap prompt
  set -- /usr/local/bin/goose-real run -s --text "$TEXT"
  [ -n "$MODEL" ] && set -- "$@" --model "$MODEL"
  exec "$@"
fi

# Restart loop: after ^C kills goose-real, restart fresh without prompt
# (hive sends the next kick via tmux send-keys)
while true; do
  set -- /usr/local/bin/goose-real run -s
  [ -n "$MODEL" ] && set -- "$@" --model "$MODEL"
  "$@" || true
done
