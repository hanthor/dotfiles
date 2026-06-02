#!/bin/sh
# goose-wrapper — translates old hive v2 goose CLI to goose v1.x CLI
#
# Old interface (from hive backends.conf):
#   goose --no-confirm [--model <model>] [<prompt>]
#
# New goose v1.x interface:
#   goose session --max-turns 100 [--model <model>]

# Collect args
ARGS=""
MODEL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-confirm) shift ;;  # skip — old permission flag
        --model) MODEL="$2"; shift 2 ;;
        *) ARGS="$ARGS $1"; shift ;;
    esac
done

# Build the new command
CMD="session --max-turns 100"
if [ -n "$MODEL" ]; then
    if [ -n "$GOOSE_PROVIDER" ]; then
        CMD="$CMD --provider $GOOSE_PROVIDER"
    fi
    CMD="$CMD --model $MODEL"
fi
if [ -n "$ARGS" ]; then
    CMD="$CMD $ARGS"
fi

exec /usr/local/bin/goose-real $CMD
