#!/usr/bin/env bash
# hive-fork-drift.sh — is tuna-os/hive (our fork, built manually into
# ghcr.io/hanthor/hive:v4-hotfix and NOT built by CI — see
# docs/src/servers/aws-k8s/cluster.md) still carrying anything upstream
# doesn't have yet?
#
# The fork exists to carry fixes ahead of kubestellar/hive until they land
# there (proxy egress timeouts + pi backend, tracked as kubestellar/hive
# #3406 and #3456 at fork-creation time). Every commit unique to the fork is
# a commit WE maintain instead of upstream CI — a manual `podman build` +
# `podman push` step that exists only because upstream hasn't merged yet.
# Once it has, the fork should be retired and hive should run a stock
# upstream image again. Nothing else checks for that day arriving, so this
# does, on a timer, and says so on the fleet Discord channel instead of
# requiring someone to remember to look.
#
# USAGE
#   hive-fork-drift.sh check    # compare branches, alert if fork is now empty
#
# State: a bare mirror clone kept locally so this doesn't grow the checked-out
# repos everyone else works in, and doesn't depend on /tmp surviving reboots.

set -u

REPO_DIR="${HIVE_FORK_DRIFT_REPO_DIR:-$HOME/.local/state/hive-fork-drift/hive.git}"
UPSTREAM=https://github.com/kubestellar/hive.git
FORK=https://github.com/tuna-os/hive.git
BRANCH="${HIVE_FORK_DRIFT_BRANCH:-v4}"
# The specific upstream PRs the fork was created to carry, per
# docs/src/servers/aws-k8s/cluster.md's tunaos-hive-checkin skill notes.
TRACKED_PRS="3406 3456"

TOKEN_NS=postgres
TOKEN_SECRET=fleet-alerts

ACTION="${1:-check}"
case "$ACTION" in check) ;; *) echo "usage: $0 check" >&2; exit 2;; esac

mkdir -p "$(dirname "$REPO_DIR")"
if [ ! -d "$REPO_DIR" ]; then
  git clone --mirror "$UPSTREAM" "$REPO_DIR" >/dev/null 2>&1 \
    || { echo "ERROR: could not clone $UPSTREAM" >&2; exit 1; }
  git -C "$REPO_DIR" remote add fork "$FORK"
fi
git -C "$REPO_DIR" fetch --prune origin "+refs/heads/*:refs/heads/*" >/dev/null 2>&1 \
  || { echo "ERROR: fetch from upstream failed" >&2; exit 1; }
git -C "$REPO_DIR" fetch --prune fork "+refs/heads/*:refs/remotes/fork/*" >/dev/null 2>&1 \
  || { echo "ERROR: fetch from fork failed" >&2; exit 1; }

AHEAD=$(git -C "$REPO_DIR" log --oneline "$BRANCH..fork/$BRANCH" 2>/dev/null)
AHEAD_N=$(printf '%s\n' "$AHEAD" | grep -vc '^$' || true)
BEHIND_N=$(git -C "$REPO_DIR" rev-list --count "fork/$BRANCH..$BRANCH" 2>/dev/null || echo 0)

echo "tuna-os/hive vs kubestellar/hive, branch $BRANCH:"
echo "  fork is $AHEAD_N commit(s) ahead, $BEHIND_N commit(s) behind"

# REST (repos/{o}/{r}/pulls/{n}), not `gh pr view`: that's GraphQL, and
# GraphQL's rate-limit bucket is shared across every agent/tool on this
# account (observed exhausted mid-session while REST still had 5000/5000
# headroom) — REST is both cheaper and the one that actually stayed up.
# curl + a minted App token, NOT `gh`. The ops image has no gh binary at all,
# so this printed "could not look up" for BOTH tracked PRs on every in-cluster
# run since the control plane moved off the workstation -- and since
# all_tracked_merged is only set when every lookup succeeds, the merged-alert
# could never fire. Both PRs had in fact been merged for weeks. A checker that
# fails silently is worse than no checker: it reports "still waiting" forever
# and you believe it. Same conversion hive-metrics.sh already got.
pr_status() {
  kubectl exec -n hive "$(kubectl get pods -n hive -l app.kubernetes.io/name=hive \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)" -- sh -c "
    PEM=/secrets/gh-app-key.pem
    B64() { openssl base64 -e -A | tr '+/' '-_' | tr -d '='; }
    NOW=\$(date +%s)
    H=\$(printf '%s' '{\"alg\":\"RS256\",\"typ\":\"JWT\"}' | B64)
    P=\$(printf '%s' \"{\\\"iat\\\":\$((NOW-60)),\\\"exp\\\":\$((NOW+540)),\\\"iss\\\":\\\"\$GH_APP_ID\\\"}\" | B64)
    S=\$(printf '%s.%s' \"\$H\" \"\$P\" | openssl dgst -sha256 -sign \$PEM | B64)
    T=\$(curl -s -X POST -H \"Authorization: Bearer \$H.\$P.\$S\" \
          https://api.github.com/app/installations/\$GH_APP_INSTALLATION_ID/access_tokens | jq -r '.token // empty')
    [ -z \"\$T\" ] && exit 1
    curl -s --max-time 30 -H \"Authorization: token \$T\" \
      https://api.github.com/repos/kubestellar/hive/pulls/$1 \
      | jq -c '{state, merged, title}'" 2>/dev/null
}
pr_lines=""
all_tracked_merged=1
for pr in $TRACKED_PRS; do
  info=$(pr_status "$pr")
  if [ -z "$info" ]; then
    pr_lines="$pr_lines  #$pr: could not look up\n"
    all_tracked_merged=0
    continue
  fi
  merged=$(printf '%s' "$info" | jq -r '.merged // empty')
  title=$(printf '%s' "$info" | jq -r '.title // empty')
  # A response that parses but carries no state is an API error object, not a
  # PR that is open. Rendering it as "open" is a failed lookup wearing the
  # costume of a definite answer -- observed live: #3456 flipped from MERGED to
  # "[open]: null" between two runs a minute apart. Unknown must suppress the
  # alert without ever being mistaken for evidence.
  if [ -z "$title" ]; then
    pr_lines="$pr_lines  #$pr [unknown]: lookup returned no state (transient API failure)\n"
    all_tracked_merged=0
    continue
  fi
  label=$([ "$merged" = true ] && echo MERGED || echo open)
  pr_lines="$pr_lines  #$pr [$label]: $title\n"
  [ "$merged" = true ] || all_tracked_merged=0
done
printf "tracked upstream PRs:\n$pr_lines"

if [ "$AHEAD_N" -eq 0 ]; then
  MSG="🎣 tuna-os/hive fork is fully absorbed upstream — 0 commits ahead of kubestellar/hive@$BRANCH. Time to point the hive deployment at a stock upstream image and retire the manual podman build/push."
elif [ "$all_tracked_merged" -eq 1 ]; then
  MSG="🎣 tuna-os/hive: the tracked upstream PRs (#$(echo $TRACKED_PRS | sed 's/ /, #/g')) are all merged, but the fork still carries $AHEAD_N other commit(s) ahead of kubestellar/hive@$BRANCH. Worth a look at whether those are also mergeable."
else
  echo "still waiting on upstream — no alert"
  exit 0
fi

echo "$MSG"

# Do NOT force KUBECONFIG in-cluster. Unconditionally exporting a workstation
# path here made every in-cluster kubectl fail, so the Discord credentials read
# below came back empty and the script reported "no Discord credentials
# available — alert logged only". There were TWO causes stacked: this
# KUBECONFIG override, and a genuinely missing RoleBinding for
# postgres/fleet-alerts (added in hive-ops.yaml).
#
# Note `kubectl auth can-i get secret/fleet-alerts -n postgres --as=<sa>`
# answered "yes" while the pod's own read returned Forbidden. The permission
# check lied; only the real operation is authoritative. Net effect before both
# fixes: the fork alert was never delivered to anyone, only printed into a
# CronJob log nobody reads.
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  export KUBECONFIG="${HIVE_FORK_DRIFT_KUBECONFIG:-$HOME/.kube/config-aws-migration}"
fi
DTOK=$(kubectl get secret -n "$TOKEN_NS" "$TOKEN_SECRET" -o jsonpath='{.data.DISCORD_BOT_TOKEN}' 2>/dev/null | base64 -d)
DCHAN=$(kubectl get secret -n "$TOKEN_NS" "$TOKEN_SECRET" -o jsonpath='{.data.DISCORD_CHANNEL}' 2>/dev/null | base64 -d)
if [ -n "$DTOK" ] && [ -n "$DCHAN" ]; then
  curl -sS -X POST -H "Authorization: Bot $DTOK" -H "Content-Type: application/json" \
    -d "$(jq -n --arg c "$MSG" '{content:$c}')" \
    "https://discord.com/api/v10/channels/$DCHAN/messages" >/dev/null \
    && echo "posted to Discord" || echo "! Discord post failed" >&2
else
  echo "! no Discord credentials available (fleet-alerts secret) — alert logged only" >&2
fi
