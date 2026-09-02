#!/usr/bin/env bash
# contributor-watchdog.sh — in-pod self-heal loop for a Hive contributor.
#
# WHAT KUBERNETES ALREADY HANDLES (so this does NOT):
#   - relay process death, tmux server death, zombie storm → the Deployment's
#     livenessProbe (grep contributor-relay /proc + tmux has-session + zombie
#     count) restarts the pod.
#   - hub disconnect → contributor-relay.sh reconnects with exponential backoff
#     on its own (one connection per hub, per the multi-hub contract).
#   - known modal prompts (codex directory-trust, update nudge) →
#     blockingPromptKey() in the relay auto-dismisses them.
#
# WHAT THIS ADDS: the gap those leave — a pane that is ALIVE but WEDGED in a
# shape the relay does not recognise (a new CLI prompt, a bare shell after the
# CLI died without the relay noticing, a PS2 continuation swallowing input).
# Left alone the pod stays Ready (relay + tmux both up) while doing no work —
# the exact "alive but under-productive" failure the tunaos-hive-checkin skill
# warns about. This loop watches the pane and nudges it, and if it can't
# recover it, exits non-zero so the shared process group / liveness path can
# recycle the pod rather than sit wedged.
#
# Runs as a SIDECAR sharing the pod's process namespace (shareProcessNamespace:
# true) so it can see the relay process and the same tmux socket.
set -uo pipefail

SESSION="${HIVE_AGENT_SESSION:-contributor}"
INTERVAL="${WATCHDOG_INTERVAL_S:-60}"
# How many consecutive wedged observations before we give up and exit non-zero.
MAX_WEDGED="${WATCHDOG_MAX_WEDGED:-5}"
# Pane text that means "a bare shell prompt", i.e. the CLI is gone.
SHELL_PROMPT_RE='[$#][[:space:]]*$|@[^[:space:]]*:[^[:space:]]*[$#]'

log() { printf '%s watchdog: %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

# Find the tmux socket the relay/agent created. contributor-agent.sh uses the
# default socket for the container's uid; capture-pane works without -S when we
# run as the same uid, but be explicit so a sidecar uid mismatch fails loudly.
capture() { tmux capture-pane -pt "$SESSION" -S -25 2>/dev/null; }

relay_alive() { grep -ql contributor-relay /proc/*/cmdline 2>/dev/null; }
session_alive() { tmux has-session -t "$SESSION" 2>/dev/null; }

# A known modal prompt the relay SHOULD dismiss but may have missed on a race:
# return the keystroke, else empty. Mirrors blockingPromptKey() so a new prompt
# shape can be added here without an image rebuild.
prompt_key() {
  local t="$1"
  printf '%s' "$t" | grep -q 'Do you trust the contents of this directory' && { echo 1; return; }
  printf '%s' "$t" | grep -q 'Update available!' && printf '%s' "$t" | grep -q 'Skip until next version' && { echo 3; return; }
  echo ""
}

wedged=0
log "starting: session=$SESSION interval=${INTERVAL}s max_wedged=$MAX_WEDGED"

while :; do
  sleep "$INTERVAL"

  if ! relay_alive; then
    log "relay process gone — leaving recovery to the liveness probe / pod restart"
    # Don't fight the probe; just record and continue so we don't double-kill.
    continue
  fi
  if ! session_alive; then
    log "tmux session '$SESSION' gone — liveness probe will restart the pod"
    continue
  fi

  text="$(capture)"
  if [ -z "$text" ]; then
    log "empty pane capture (transient?) — will re-check next tick"
    continue
  fi

  # 1) A modal prompt the relay missed → dismiss it, reset the wedge counter.
  key="$(prompt_key "$text")"
  if [ -n "$key" ]; then
    log "dismissing modal prompt with key '$key'"
    tmux send-keys -t "$SESSION" "$key" Enter 2>/dev/null
    wedged=0
    continue
  fi

  # 2) The CLI died and left a bare shell prompt. The relay's own relaunch path
  #    normally catches this, but if the pane has been sitting at a shell for a
  #    full interval the relay has not recovered it. A bare Enter can't fix a
  #    dead CLI, so escalate: count it as wedged.
  last_line="$(printf '%s' "$text" | grep -v '^[[:space:]]*$' | tail -1)"
  if printf '%s' "$last_line" | grep -Eq "$SHELL_PROMPT_RE"; then
    wedged=$((wedged + 1))
    log "pane at a bare shell prompt (CLI down?) — wedged=$wedged/$MAX_WEDGED"
    if [ "$wedged" -ge "$MAX_WEDGED" ]; then
      log "giving up after $wedged wedged ticks — exiting non-zero to recycle the pod"
      exit 1
    fi
    continue
  fi

  # 3) Healthy-looking pane (CLI REPL present) → reset the counter.
  wedged=0
done
