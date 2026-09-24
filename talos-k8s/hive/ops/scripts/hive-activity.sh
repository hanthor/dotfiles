#!/usr/bin/env bash
# hive-activity.sh — snapshot what the fleet is doing into activity.json for
# the hub front page (hub.tunaos.org "Live activity" section).
#
# SOURCES (one kubectl exec per spoke per source — no per-agent fan-out):
#   spokes  /api/status via X-Hive-Internal (id, level, per-agent cli/model/
#           paused/busy — the feed's "who is working" strip)
#   beads   /data/beads/*/beads.json filtered in-pod to the recent window
#   registry  hub /api/registry (in-cluster DNS): per-repo issue/pr/comment/
#             merge/review counts + per-agent breakdowns, no GitHub auth needed
#
# Every section is BEST-EFFORT with a null fallback so the frontend can say
# what is missing instead of the job lying by omission. An honest gap beats
# a silent one.
#
# PUBLISH writes only the activity.json key of the hub-front ConfigMap
# (get | jq | replace), never the whole object — index.html lives there too
# and is owned by talos-k8s/hive-hub/front/index.html, not by this job.
#
# USAGE
#   hive-activity.sh snapshot   # print activity.json to stdout, no writes
#   hive-activity.sh publish    # snapshot + publish to hub-front ConfigMap
#
# Env:
#   HIVE_ACTIVITY_BEAD_HOURS  bead window in hours (default 72)

# shellcheck source=hive-lib.sh
. "${HIVE_LIB:-$(dirname "$0")/hive-lib.sh}"
hive_kube_env

set -u

ACTION="${1:-snapshot}"
case "$ACTION" in snapshot|publish) ;; *) echo "usage: $0 snapshot|publish" >&2; exit 2;; esac

BEAD_HOURS="${HIVE_ACTIVITY_BEAD_HOURS:-72}"
# Scratch on DISK, never /tmp: /tmp is a small tmpfs that fills (observed
# 100% full 2026-09-23) and mktemp/jq then die confusingly mid-run.
STATE_DIR="${HIVE_ACTIVITY_STATE:-$HOME/.local/state/hive-activity}"
mkdir -p "$STATE_DIR/tmp"
TMP=$(mktemp -d "$STATE_DIR/tmp/act.XXXXXX")
trap 'rm -rf "$TMP"' EXIT

# Namespace -> short spoke name for the feed.
SPOKES="hive:school hive-reef:reef hive-hanthor:hanthor"

# ── Spokes + beads (in-cluster reads, no egress needed) ────────────────────
: > "$TMP/spokes.jsonl"
: > "$TMP/beads.jsonl"

for pair in $SPOKES; do
  ns="${pair%%:*}"; spoke="${pair##*:}"
  # Slim status via the hive Service (hive-lib.sh). The old exec read of the
  # 3 MB v5 /api/status with --max-time 25 truncated, and `|| true` then
  # silently dropped the spoke from the feed.
  hive_open "$ns" 2>/dev/null || { echo "WARN: $spoke status unreadable — omitted" >&2; continue; }
  pod=$POD
  printf '%s' "$STATUS_JSON" | jq --arg spoke "$spoke" '{
      spoke: $spoke, hiveId: (.hiveId // null), acmmLevel,
      governorMode: .governorMode,
      agents: [.agents[] | {name, cli, model, paused, busy, state}]
    }' 2>/dev/null >> "$TMP/spokes.jsonl" || true

  # Beads: filter + trim INSIDE the pod (the store is ~7MB per spoke).
  # GNU date first, python3 fallback — the image has at least one.
  kubectl exec -n "$ns" "$pod" -- sh -c '
    cutoff=$(date -u -d "'"$BEAD_HOURS"' hours ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) \
      || cutoff=$(python3 -c "import datetime;print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours='"$BEAD_HOURS"')).strftime(\"%Y-%m-%dT%H:%M:%SZ\"))")
    for f in /data/beads/*/beads.json; do
      a=$(basename "$(dirname "$f")")
      jq --arg a "$a" --arg c "$cutoff" --arg s "'"$spoke"'" "
        [ .[] | select(.updated_at > \$c)
        | {spoke: \$s, agent: \$a, id, title, type, status, priority,
           updated: .updated_at} ]
        | sort_by(.updated) | reverse | .[:12]" "$f" 2>/dev/null
    done' 2>/dev/null | jq -s 'add // []' >> "$TMP/beads.jsonl" || true
done

# ── Hub registry: repo activity + hive vitals (best-effort) ─────────────────
# The hub already aggregates per-repo issues/prs/comments/merges/reviews with
# per-agent breakdowns — no GitHub credential needed. In-cluster DNS first
# (no egress dependency), public URL as fallback for workstation runs.
#
# NOTE: item-level enrichment (PR titles, comment bodies) via the GitHub API
# is parked: the App private key in hive-secrets 401s on /app as a JWT —
# from the pod and the workstation alike — while the hive's own traffic still
# succeeds. Key rotation is a human+GitHub-UI action; until then the feed
# shows counts+newestAt (honest aggregates) instead of item bodies.
# SUBSHELL on purpose: a failure must degrade to null, never abort the run.
: > "$TMP/registry.json"
(
  reg=""
  for ru in "http://hive-hub.hive-hub.svc:3001/api/registry" \
            "https://hub.tunaos.org/api/registry"; do
    reg=$(curl -sS --max-time 20 "$ru" 2>/dev/null \
            | jq -e '.hives | length > 0' >/dev/null 2>&1 \
            && curl -sS --max-time 20 "$ru" 2>/dev/null) && break
  done
  [ -n "$reg" ] || exit 1
  printf '%s' "$reg" | jq '{
    hives: [.hives[] | {
      id, org, acmmLevel, governorMode, agentCount, online, lastHeartbeat,
      totalTokens24h, actionableIssues, actionablePRs, tasksCompleted7d,
      awaitingReview, prsMerged90d,
      repoActivity: ([.repoActivity[]? | select(
          (.issues.count // 0) + (.prs.count // 0) + (.comments.count // 0) +
          (.merges.count // 0) + (.reviews.count // 0) > 0)
        | {repo,
           issues: (if (.issues.count // 0) > 0 then .issues else null end),
           prs: (if (.prs.count // 0) > 0 then .prs else null end),
           comments: (if (.comments.count // 0) > 0 then .comments else null end),
           merges: (if (.merges.count // 0) > 0 then .merges else null end),
           reviews: (if (.reviews.count // 0) > 0 then .reviews else null end),
           agents: ([.agents[]? | select(
              (.issues.count // 0) + (.prs.count // 0) + (.comments.count // 0) +
              (.merges.count // 0) + (.reviews.count // 0) > 0)
            | {agent} + .] | .[:4])}
      ] | sort_by(.repo) | .[:25])
    }]
  }' > "$TMP/registry.json" 2>/dev/null || exit 1
  [ -s "$TMP/registry.json" ] || exit 1
) || echo '{"hives": []}' > "$TMP/registry.json"

# ── Assemble ────────────────────────────────────────────────────────────────
jq -n --slurpfile spokes "$TMP/spokes.jsonl" --slurpfile beads "$TMP/beads.jsonl" \
      --slurpfile reg "$TMP/registry.json" '{
  generated_at: (now | todate),
  spokes: ($spokes | map(select(.spoke != null))),
  beads: (($beads | add // []) | sort_by(.updated) | reverse | .[:80]),
  registry: ($reg[0] | if (.hives // []) == [] then null else . end)
}' > "$TMP/activity.json"

if [ "$ACTION" = snapshot ]; then
  cat "$TMP/activity.json"
  exit 0
fi

# Publish: replace ONLY the activity.json key, preserving index.html etc.
# Retry once on resourceVersion conflict.
for _try in 1 2; do
  if kubectl get configmap hub-front -n hive-hub -o json 2>/dev/null \
     | jq --rawfile act "$TMP/activity.json" '.data["activity.json"] = $act' \
     | kubectl replace -f - >/dev/null 2>&1; then
    echo "published activity.json ($(wc -c < "$TMP/activity.json") bytes)"
    exit 0
  fi
  sleep 5
done
echo "ERROR: could not publish hub-front ConfigMap" >&2
exit 1
