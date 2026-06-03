#!/bin/sh
# goose-wrapper — launches goose v1.x with DeepSeek provider.
# Handles hive compatibility: --no-confirm flag, telemetry prompt,
# and prints hive's expected "Environment loaded" ready marker.

set -e

# Pre-configure goose for DeepSeek (first run only)
if [ ! -f /home/dev/.config/goose/config.yaml ]; then
    mkdir -p /home/dev/.config/goose /home/dev/.local/state/goose
    cat > /home/dev/.config/goose/config.yaml << 'YAML'
provider: custom_deepseek
model: deepseek-v4-pro
YAML
    echo '{"telemetry_enabled":false,"configured":true}' > /home/dev/.local/state/goose/state.json
fi

# Drop old flags that goose v1.x doesn't support
while [ $# -gt 0 ]; do
    case "$1" in
        --no-confirm) shift ;;
        --model) shift 2 ;;
        *) shift ;;
    esac
done

# Print hive's expected ready markers
echo "DeepSeek chat ready ❯"
echo "Environment loaded"

# Launch goose with TTY for the telemetry prompt (first-run only).
# (echo y; cat) answers "y" then keeps stdin open via cat so hive
# kicks sent via tmux send-keys reach goose.
exec sh -c '(echo y; exec cat) | exec script -q -c "/usr/local/bin/goose-real session --max-turns 100" /dev/null'
