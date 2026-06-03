#!/bin/sh
# goose-wrapper — launches goose v1.x with DeepSeek provider.
# Handles hive compatibility: --no-confirm flag, telemetry prompt.

set -e

# Pre-configure goose for DeepSeek
mkdir -p /home/dev/.config/goose /home/dev/.local/state/goose
cat > /home/dev/.config/goose/config.yaml << 'YAML'
provider: custom_deepseek
model: deepseek-v4-pro
YAML
echo '{"telemetry_enabled":false,"configured":true,"provider":"custom_deepseek"}' > /home/dev/.local/state/goose/state.json

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

# Answer telemetry prompt then keep stdin open via cat
(echo y; exec cat) | exec /usr/local/bin/goose-real session --max-turns 100
