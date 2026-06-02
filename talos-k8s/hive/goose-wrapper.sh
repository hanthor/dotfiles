#!/bin/sh
# goose-wrapper — tries goose v1.x with native DeepSeek support.
# Falls back to Python deepseek-chat.py if goose isn't available.

set -e

# If goose-real exists, use it with proper config
if [ -x /usr/local/bin/goose-real ]; then
    # Pre-configure goose for DeepSeek (first run only)
    if [ ! -f /home/dev/.config/goose/config.yaml ]; then
        mkdir -p /home/dev/.config/goose /home/dev/.local/state/goose
        cat > /home/dev/.config/goose/config.yaml << 'YAML'
provider: custom_deepseek
model: deepseek-v4-pro
YAML
        echo '{"telemetry_enabled":false,"configured":true}' > /home/dev/.local/state/goose/state.json
    fi

    # Drop old flags, run goose session with TTY
    while [ $# -gt 0 ]; do
        case "$1" in
            --no-confirm) shift ;;
            --model) shift 2 ;;
            *) shift ;;
        esac
    done

    export GOOSE_PROVIDER=custom_deepseek
    exec script -q -c "/usr/local/bin/goose-real session --max-turns 100" /dev/null
fi

# Fallback: Python DeepSeek chat loop
exec python3 /usr/local/bin/deepseek-chat.py "$@"
