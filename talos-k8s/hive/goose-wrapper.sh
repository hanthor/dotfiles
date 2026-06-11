#!/bin/sh
# goose-wrapper: translates old hive CLI interface to goose 1.37.0 subcommands,
# and runs goose in a restart loop so that ^C (clear_on_kick) doesn't kill
# the tmux session — only goose-real dies and restarts.
#
# Upstream Go binary calls: goose --model X --prompt "$(cat /tmp/prompt.txt)"
# We rewrite to:          goose-real run -s --model X --text "..."

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

# First launch: include the bootstrap prompt if provided
if $HAD_PROMPT && [ -n "$TEXT" ]; then
  /usr/local/bin/goose-real run -s --text "$TEXT" ${MODEL:+--model "$MODEL"} || true
fi

# Restart loop: after ^C kills goose-real, restart fresh without prompt
# (hive sends the next kick via tmux send-keys to the pane)
while true; do
  /usr/local/bin/goose-real run -s ${MODEL:+--model "$MODEL"} || true
done
