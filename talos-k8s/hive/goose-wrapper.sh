#!/bin/sh
# goose-wrapper — runs goose v1.x in a restart loop so clear_on_kick works.
#
# Why no script(1) or pipe: piping 'y' to script closes stdin after telemetry,
# so tmux send-keys can't reach goose. Running goose-real directly means the
# tmux PTY is goose's stdin — send-keys delivers boot/kick prompts correctly.
#
# Why the loop: clear_on_kick sends ^C to kill the running session. trap '' INT
# makes the wrapper ignore SIGINT so only goose-real is killed. The loop then
# re-emits the ready markers the Go binary watches for before sending the next
# prompt via send-keys.

# Ignore SIGINT: ^C from clear_on_kick kills goose-real but not this wrapper.
trap '' INT

# Drop old hive-specific flags that goose-real doesn't understand.
while [ $# -gt 0 ]; do
    case "$1" in
        --no-confirm) shift ;;
        --model) shift 2 ;;
        --prompt) shift 2 ;;
        *) shift ;;
    esac
done

# Pre-configure goose. Delete + recreate to work around root-owned config.yaml
# (goose self-writes its config on first run as root in some code paths).
# Dev owns the directory so it can unlink root-owned files; recreating gives
# us a dev-owned file we can manage on future runs.
GOOSE_CFG=/home/dev/.config/goose/config.yaml
mkdir -p "$(dirname "$GOOSE_CFG")" /home/dev/.local/state/goose
rm -f "$GOOSE_CFG"
cat > "$GOOSE_CFG" << 'YAML'
provider: custom_deepseek
model: deepseek-chat
GOOSE_TELEMETRY_ENABLED: false
YAML

# Loop: emit ready markers, run goose-real, restart on exit.
# The Go binary detects the ready markers then delivers prompts via send-keys.
while true; do
    echo "DeepSeek chat ready ❯"
    echo "Environment loaded"
    /usr/local/bin/goose-real session --max-turns 100 || true
done
