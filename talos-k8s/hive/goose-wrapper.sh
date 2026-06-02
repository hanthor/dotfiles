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

# Launch goose with TTY (script provides pseudo-TTY for telemetry prompt)
# Answer "y" to telemetry on first run, then goose stays interactive.
exec script -q -c "/usr/local/bin/goose-real session --max-turns 100" /dev/null << 'GOOSE_INPUT'
y
GOOSE_INPUT
