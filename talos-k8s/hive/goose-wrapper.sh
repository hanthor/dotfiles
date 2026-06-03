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

# Start the DeepSeek proxy on first run (one proxy per pod, shared by all agents).
# The proxy injects thinking:{type:disabled} so goose never sees reasoning_content.
PROXY_PORT=15432
PROXY_PID_FILE=/tmp/.deepseek-proxy.pid
if [ ! -f "$PROXY_PID_FILE" ] || ! kill -0 "$(cat "$PROXY_PID_FILE")" 2>/dev/null; then
    python3 /etc/hive/deepseek-proxy.py &
    echo $! > "$PROXY_PID_FILE"
fi

GOOSE_CFG=/home/dev/.config/goose/config.yaml
mkdir -p "$(dirname "$GOOSE_CFG")" /home/dev/.local/state/goose
rm -f "$GOOSE_CFG"
cat > "$GOOSE_CFG" << 'YAML'
provider: litellm
model: deepseek-v4-flash
GOOSE_TELEMETRY_ENABLED: false
YAML

# Switch to litellm provider — unlike custom_deepseek (hardcoded base_url),
# litellm respects LITELLM_HOST so we can route through our local proxy.
export GOOSE_PROVIDER=litellm
export LITELLM_HOST=http://127.0.0.1:15432
export LITELLM_API_KEY=$DEEPSEEK_API_KEY

# Loop: emit ready markers, run goose-real, restart on exit.
# The Go binary detects the ready markers then delivers prompts via send-keys.
while true; do
    echo "DeepSeek chat ready ❯"
    echo "Environment loaded"
    /usr/local/bin/goose-real session --max-turns 100 || true
done
