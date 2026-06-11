#!/bin/sh
# goose-wrapper: translates old hive CLI interface to goose 1.37.0 subcommands.
#
# Upstream Go binary calls: goose --model X --prompt "$(cat /tmp/prompt.txt)"
# We rewrite to:          goose-real run -s --no-session --model X --text "..."
#
# The shell expands $(cat file) before calling this wrapper, so --prompt's
# argument is the full multiline content as a single shell word.

set -e

MODEL=""
TEXT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --prompt) TEXT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

set -- /usr/local/bin/goose-real run -s --no-session
[ -n "$MODEL" ] && set -- "$@" --model "$MODEL"
[ -n "$TEXT" ] && set -- "$@" --text "$TEXT"

exec "$@"
