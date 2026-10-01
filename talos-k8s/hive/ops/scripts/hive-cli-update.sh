#!/usr/bin/env bash
# hive-cli-update.sh — keep the agent CLIs current across every spoke.
#
# WHY
# ---
# The CLIs are the fleet. A stale pi/codex/agy/claude is not a cosmetic lag: the
# backends gain and drop model ids between releases, and hive-inventory.sh reads
# those lists to gate the rung ladder. An old CLI therefore makes new models
# invisible to rotation no matter what the benchmark feed says. Found 2026-09-06
# with pi pinned at 0.84.1 while 0.85.1 was out.
#
# WHAT THIS CANNOT DO, AND WHY IT STILL RUNS DAILY
# ------------------------------------------------
# /usr/local/bin is the container's OVERLAY filesystem, not a volume. Updates
# are writable but are LOST on every pod restart, reverting to whatever the
# image shipped. There is no fix for that here — persisting them would mean
# installing to a PVC and owning PATH for every agent user, or rebuilding the
# image. So this is a reconciler, not an installer: it re-applies after a
# restart on the next pass, and the version line it prints is the signal for how
# far the image itself has drifted.
#
# RISK, STATED PLAINLY: this auto-installs third-party releases into a running
# fleet. A bad release wedges agents. The mitigation is hive-rotate.sh's
# watchdog, which classifies dead panes every 5 minutes and heals them, plus the
# fact that a revert is one pod restart away. Set HIVE_CLI_UPDATE_TARGETS="" to
# disable without deleting the CronJob.
#
# USAGE
#   hive-cli-update.sh update    # update, then report versions
#   hive-cli-update.sh report    # report versions only, change nothing

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

set -u

LABEL=app.kubernetes.io/name=hive
NAMESPACES="${HIVE_CLI_UPDATE_NAMESPACES:-hive hive-reef hive-hanthor}"
# Only pi is updated by default. codex/claude/agy each ship their own updater
# but are the backends currently carrying the fleet — add them deliberately,
# not by default, so one bad release cannot take every provider at once.
TARGETS="${HIVE_CLI_UPDATE_TARGETS:-pi}"
ACTION="${1:-report}"
case "$ACTION" in update|report) ;; *) echo "usage: $0 update|report" >&2; exit 2;; esac

rc=0
for ns in $NAMESPACES; do
  pod=$(kubectl get pods -n "$ns" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  if [ -z "$pod" ]; then
    printf '%-14s no hive pod — skipped\n' "$ns"
    continue
  fi

  for cli in $TARGETS; do
    before=$(kubectl exec -n "$ns" "$pod" -- sh -c \
      "command -v $cli >/dev/null && timeout 20 $cli --version 2>/dev/null | head -1" 2>/dev/null)
    if [ -z "$before" ]; then
      printf '%-14s %-6s not installed — skipped\n' "$ns" "$cli"
      continue
    fi

    if [ "$ACTION" = report ]; then
      printf '%-14s %-6s %s\n' "$ns" "$cli" "$before"
      continue
    fi

    # Each CLI has its own updater; there is no common interface.
    case "$cli" in
      pi)    cmd='HOME=/data/home timeout 240 pi update --self' ;;
      codex) cmd='HOME=/data/home timeout 240 codex update' ;;
      *)     printf '%-14s %-6s no known updater — skipped\n' "$ns" "$cli"; continue ;;
    esac

    if ! out=$(kubectl exec -n "$ns" "$pod" -- sh -c "$cmd" 2>&1); then
      printf '%-14s %-6s UPDATE FAILED: %s\n' "$ns" "$cli" "$(printf '%s' "$out" | tail -1)"
      rc=1
      continue
    fi
    after=$(kubectl exec -n "$ns" "$pod" -- sh -c \
      "timeout 20 $cli --version 2>/dev/null | head -1" 2>/dev/null)
    if [ "$before" = "$after" ]; then
      printf '%-14s %-6s already current (%s)\n' "$ns" "$cli" "$after"
    else
      printf '%-14s %-6s %s -> %s\n' "$ns" "$cli" "$before" "$after"
    fi
  done
done
exit $rc
