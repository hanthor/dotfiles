#!/bin/sh
# pi-wrapper — runs pi (coding agent) in a restart loop so clear_on_kick works.
#
# Replaces goose-wrapper.sh. Pi natively supports DeepSeek — no proxy needed.
#
# Why the loop: clear_on_kick sends ^C to kill the running session. trap '' INT
# makes the wrapper ignore SIGINT so only pi-real is killed. The loop then
# re-emits the ready markers the Go binary watches for before sending the next
# prompt via send-keys.
#
# Boot/kick prompts arrive via tmux send-keys, not CLI args. Hive writes text
# into the tmux pane; pi's interactive editor receives it, Enter submits.

# Ignore SIGINT: ^C from clear_on_kick kills pi-real but not this wrapper.
trap '' INT

# ── Parse CLI args (Hive passes --no-confirm, --model, --prompt) ──────
# agent-launch.sh assembles: pi --no-confirm --model deepseek-v4-pro
# We strip --no-confirm (pi has no permission popups) and extract the model.
MODEL="deepseek-v4-pro"
while [ $# -gt 0 ]; do
    case "$1" in
        --no-confirm) shift ;;  # pi doesn't need this — no permission popups
        --model) MODEL="$2"; shift 2 ;;
        --prompt) shift 2 ;;   # boot prompt comes via send-keys, not CLI
        *) shift ;;
    esac
done

# ── pi config (DeepSeek native) ───────────────────────────────────────
PI_CONFIG_DIR="${PI_CODING_AGENT_DIR:-/home/dev/.pi/agent}"
mkdir -p "$PI_CONFIG_DIR"
cat > "$PI_CONFIG_DIR/settings.json" << 'JSON'
{
  "defaultProvider": "deepseek",
  "defaultModel": "deepseek-v4-pro",
  "quietStartup": true,
  "hideThinkingBlock": true,
  "enableInstallTelemetry": false
}
JSON

# ── Ensure DeepSeek API key is exported ───────────────────────────────
# Hive already sets DEEPSEEK_API_KEY from the secret.
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "WARNING: DEEPSEEK_API_KEY not set" >&2
fi

# ── Session directory (persistent across restarts) ────────────────────
SESSION_DIR="/data/pi-sessions/${HIVE_AGENT:-agent}"
mkdir -p "$SESSION_DIR"

# ── Main loop: emit ready markers, run pi, restart on exit ────────────
# The Go binary detects the ready markers (">" and "Environment loaded"),
# then delivers boot/kick prompts via tmux send-keys.
#
# pi interactive TUI: text from send-keys lands in the editor, Enter submits.
# Tools auto-execute (pi has no permission popups). Session persists in
# $SESSION_DIR across restarts.
while true; do
    echo "pi chat ready ❯"
    echo "Environment loaded"

    /usr/local/bin/pi-real \
        --provider deepseek \
        --model "$MODEL" \
        --no-context-files \
        --session-dir "$SESSION_DIR" || true
done
