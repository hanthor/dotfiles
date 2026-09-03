#!/usr/bin/env bash
# hive-inventory.sh — what each backend can ACTUALLY run, right now.
#
# WHY THIS EXISTS, SEPARATELY FROM hive-tiers.sh
# ----------------------------------------------
# hive-tiers.sh answers "which models are GOOD" from a benchmark API.
# This answers "which models EXIST and are runnable by the CLI in this pod".
# They are different questions and each is useless alone:
#
#   - A benchmark ranking can name a model this fleet cannot launch. Rotation
#     then places an agent on an id the CLI rejects, which presents as a dead
#     agent, not as a config error.
#   - An inventory can name a model nobody has benchmarked, so it never gets
#     tiered and is never used no matter how good it is.
#
# The tier ladder should be rank(inventory INTERSECT benchmark), with inventory
# as the GATE: never emit a rung whose id the backend does not offer.
#
# Measured 2026-09-03, which is what prompted this: agy had shipped
# gemini-3.8-flash-{high,medium,low} while the hardcoded table still pinned
# 3.7 and 3.6, and anthropic's model list carried claude-fable-5-1 that the
# table had never heard of. Nothing in the fleet noticed, because nothing was
# looking. A hardcoded ladder does not fail loudly when a vendor ships — it
# just quietly keeps using last season's model.
#
# WHERE THE TRUTH LIVES, PER BACKEND
# ----------------------------------
#   agy        `agy models`            — the CLI's own list. Authoritative:
#                                        it is literally what --model accepts.
#   anthropic  GET /v1/models          — with the SAME OAuth token the usage
#                                        probe uses; no extra credential.
#   deepseek   GET /models             — with DEEPSEEK_API_KEY from the pod env.
#   openai     (none)                  — codex authenticates by subscription and
#                                        exposes no list; there is no API key in
#                                        this deployment. Reported as unknown
#                                        rather than guessed, so a consumer can
#                                        tell "no models" from "not measured".
#
# Every lookup is best-effort and independently fallible. A backend that cannot
# be inventoried contributes NO rows and is recorded in the note column — it
# must never cause an empty inventory to be published, because a consumer that
# gates on inventory would then refuse every rung and strand the fleet.
#
# USAGE
#   hive-inventory.sh            # collect, write cache, publish ConfigMap
#   hive-inventory.sh show       # print the current cache
#
# Output TSV: provider <TAB> backend <TAB> model_id <TAB> display_name

set -u

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

NS="${HIVE_NS:-hive}"
LABEL=app.kubernetes.io/name=hive
STATE_DIR="${HIVE_INVENTORY_STATE:-${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}}"
CACHE="$STATE_DIR/inventory.tsv"
mkdir -p "$STATE_DIR"

ACTION="${1:-collect}"
case "$ACTION" in collect|show) ;; *) echo "usage: $0 collect|show" >&2; exit 2 ;; esac

if [ "$ACTION" = show ]; then
  [ -s "$CACHE" ] || { echo "no inventory at $CACHE — run '$0 collect'" >&2; exit 1; }
  printf '%-10s %-8s %-28s %s\n' PROVIDER BACKEND MODEL_ID DISPLAY
  awk -F'\t' '!/^#/ {printf "%-10s %-8s %-28s %s\n",$1,$2,$3,$4}' "$CACHE"
  exit 0
fi

POD=$(kubectl get pods -n "$NS" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$POD" ] || { echo "ERROR: no hive pod in $NS" >&2; exit 1; }

TMP="$CACHE.tmp"
: > "$TMP"
NOTES=""

# ── agy ─────────────────────────────────────────────────────────────────
# `agy models` prints "<id>\t<Display Name>" after a "Fetching…" line. Run as a
# real agent user so it sees the shared /data/home config; running as root gets
# a different (and wrong) home.
agy_rows=$(kubectl exec -n "$NS" "$POD" -- su -s /bin/sh hive-guide -c \
             'timeout 60 agy models 2>/dev/null' 2>/dev/null \
           | awk -F'\t' 'NF==2 && $1 ~ /^[a-z0-9][a-z0-9.-]*$/ {print}')
if [ -n "$agy_rows" ]; then
  printf '%s\n' "$agy_rows" | while IFS=$'\t' read -r id disp; do
    printf 'google\tagy\t%s\t%s\n' "$id" "$disp" >> "$TMP"
  done
else
  NOTES="$NOTES agy:unreadable"
fi

# ── anthropic ───────────────────────────────────────────────────────────
# Same OAuth token as the usage probe. It stays inside the pod; only the model
# list crosses the exec boundary.
ant_rows=$(kubectl exec -n "$NS" "$POD" -- su-exec 2010 sh -c '
  TOK=$(jq -r ".claudeAiOauth.accessToken // empty" /data/home/.claude/.credentials.json 2>/dev/null)
  [ -z "$TOK" ] && exit 1
  curl -s --max-time 20 -H "Authorization: Bearer $TOK" \
       -H "anthropic-beta: oauth-2025-04-20" -H "anthropic-version: 2023-06-01" \
       https://api.anthropic.com/v1/models' 2>/dev/null \
  | jq -r 'try (.data[]? | "\(.id)\t\(.display_name // .id)") // empty' 2>/dev/null)
if [ -n "$ant_rows" ]; then
  printf '%s\n' "$ant_rows" | while IFS=$'\t' read -r id disp; do
    printf 'anthropic\tclaude\t%s\t%s\n' "$id" "$disp" >> "$TMP"
  done
else
  NOTES="$NOTES anthropic:unreadable"
fi

# ── deepseek ────────────────────────────────────────────────────────────
ds_rows=$(kubectl exec -n "$NS" "$POD" -- sh -c \
            'curl -s --max-time 20 -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
               https://api.deepseek.com/models' 2>/dev/null \
          | jq -r 'try (.data[]? | .id) // empty' 2>/dev/null)
if [ -n "$ds_rows" ]; then
  printf '%s\n' "$ds_rows" | while read -r id; do
    printf 'deepseek\tpi\t%s\t%s\n' "$id" "$id" >> "$TMP"
  done
else
  NOTES="$NOTES deepseek:unreadable"
fi

# ── openai ──────────────────────────────────────────────────────────────
# Deliberately not guessed. codex authenticates by subscription and offers no
# list, and there is no OpenAI API key here. "Unknown" is a different state
# from "empty" and consumers must be able to tell them apart.
NOTES="$NOTES openai:no-list-endpoint"

rows=$(grep -c . "$TMP" 2>/dev/null || echo 0)
# An empty collection is NEVER published over a good cache. A consumer that
# gates rung emission on this file would refuse every model and strand the
# whole fleet — the failure mode has to be "keep yesterday's inventory", not
# "believe nothing exists".
if [ "$rows" -lt 1 ]; then
  echo "ERROR: inventory came back empty ($NOTES) — keeping previous cache" >&2
  rm -f "$TMP"
  exit 1
fi

{
  echo "# generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by hive-inventory.sh"
  echo "# notes:$NOTES"
  cat "$TMP"
} > "$CACHE"
rm -f "$TMP"

echo "inventory: $rows model(s)$NOTES"
awk -F'\t' '!/^#/ {c[$1]++} END {for (p in c) printf "  %-10s %d\n", p, c[p]}' "$CACHE"

# Publish for the console / operator visibility. Best-effort: a failed publish
# must never fail the collection that already succeeded.
kubectl create configmap hive-model-inventory -n "$NS" \
  --from-file=inventory.tsv="$CACHE" \
  --from-literal=updated_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --from-literal=notes="${NOTES:-none}" \
  --dry-run=client -o yaml 2>/dev/null | kubectl apply -f - >/dev/null 2>&1 \
  || echo "WARN: could not publish hive-model-inventory ConfigMap" >&2
