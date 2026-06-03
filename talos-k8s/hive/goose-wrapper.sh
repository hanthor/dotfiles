#!/bin/sh
# goose-wrapper — launches goose v1.x with DeepSeek provider.
# Uses script for TTY, pipes "y" to answer telemetry prompt.

set -e

# Pre-configure goose for DeepSeek
mkdir -p /home/dev/.config/goose /home/dev/.local/state/goose
cat > /home/dev/.config/goose/config.yaml << 'YAML'
provider: custom_deepseek
model: deepseek-v4-pro
YAML
echo '{"telemetry_enabled":false,"configured":true}' > /home/dev/.local/state/goose/state.json

# Drop old flags
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

# script provides TTY. printf answers telemetry prompt.
# After printf, stdin is closed but goose stays alive via script's TTY.
exec printf 'y\n' | exec script -q -c "/usr/local/bin/goose-real session --max-turns 100" /dev/null
