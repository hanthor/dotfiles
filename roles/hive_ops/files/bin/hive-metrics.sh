#!/usr/bin/env bash
# hive-metrics.sh — publish the hive bot's daily PR/issue flow as a ConfigMap
# for hive-console to chart.
#
# WHY A COLLECTOR AND NOT A CONSOLE QUERY
# ---------------------------------------
# The console renders on page load; GitHub's SEARCH api allows ~30 requests a
# minute and this needs 4 per day of history. Querying on render would make the
# page slow, rate-limit under refreshes, and put a GitHub credential in a pod
# that currently needs none. Collecting on a timer and publishing the result
# keeps the console a pure reader — the same split already used for
# hive-provider-usage.
#
# WHY total_count PER DAY, NOT PAGINATION
# ---------------------------------------
# Search caps pagination at 1000 results, and this fleet already exceeds that
# over the window (1068 PRs opened in 30 days). `total_count` for a
# single-day range is exact and costs one request regardless of volume, so the
# arithmetic stays right as the fleet gets busier.
#
# USAGE
#   hive-metrics.sh collect    # query GitHub and publish the ConfigMap
#   hive-metrics.sh show       # print what is currently published
#
# Env:
#   HIVE_METRICS_DAYS   days of history (default 14)
#   HIVE_METRICS_ORG    GitHub org (default tuna-os)
#   HIVE_METRICS_BOT    search author (default app/hanthor-hive-agent)

: "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
export KUBECONFIG

set -u

NS=hive
CM=hive-activity-series
DAYS="${HIVE_METRICS_DAYS:-14}"
ORG="${HIVE_METRICS_ORG:-tuna-os}"
BOT="${HIVE_METRICS_BOT:-app/hanthor-hive-agent}"

ACTION="${1:-collect}"
case "$ACTION" in collect|show) ;; *) echo "usage: $0 collect|show" >&2; exit 2;; esac

if [ "$ACTION" = show ]; then
  kubectl get configmap -n "$NS" "$CM" -o jsonpath='{.data}' 2>/dev/null | jq . || echo "not published yet"
  exit 0
fi

command -v gh >/dev/null || { echo "ERROR: gh not on PATH" >&2; exit 1; }

# count <extra-query> <field> <day>
# Search is REST here on purpose: `gh search`/`gh pr list` are GraphQL, and the
# GraphQL bucket is shared with everything else on this account — it was
# observed exhausted mid-session while REST still had its full 5000. REST also
# gives total_count directly.
count() {
  local extra="$1" field="$2" day="$3" out
  out=$(gh api -X GET search/issues \
        -f q="org:$ORG author:$BOT $extra $field:$day" \
        --jq '.total_count' 2>/dev/null)
  case "$out" in ''|*[!0-9]*) echo 0 ;; *) echo "$out" ;; esac
}

days=""; pr_open=""; pr_merged=""; is_open=""; is_closed=""
i=$((DAYS - 1))
while [ "$i" -ge 0 ]; do
  d=$(date -u -d "-$i day" +%Y-%m-%d 2>/dev/null) || d=$(date -u -v-"$i"d +%Y-%m-%d)
  days="$days,\"$d\""
  pr_open="$pr_open,$(count 'type:pr' created "$d")"
  pr_merged="$pr_merged,$(count 'type:pr is:merged' merged "$d")"
  is_open="$is_open,$(count 'type:issue' created "$d")"
  is_closed="$is_closed,$(count 'type:issue is:closed' closed "$d")"
  # Stay under the search API's ~30/min: 4 requests per day of history.
  sleep 2
  i=$((i - 1))
done

j() { printf '[%s]' "${1#,}"; }
PAYLOAD=$(jq -n \
  --argjson days "$(j "$days")" \
  --argjson pr_opened "$(j "$pr_open")" \
  --argjson pr_merged "$(j "$pr_merged")" \
  --argjson issues_opened "$(j "$is_open")" \
  --argjson issues_closed "$(j "$is_closed")" \
  --arg updated_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg org "$ORG" \
  '{days:$days, pr_opened:$pr_opened, pr_merged:$pr_merged,
    issues_opened:$issues_opened, issues_closed:$issues_closed,
    updated_at:$updated_at, org:$org}')

printf '%s' "$PAYLOAD" | jq -e . >/dev/null 2>&1 \
  || { echo "ERROR: built an invalid payload" >&2; exit 1; }

kubectl create configmap "$CM" -n "$NS" \
  --from-literal=series.json="$PAYLOAD" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null \
  || { echo "ERROR: could not publish $CM" >&2; exit 1; }

printf '%s' "$PAYLOAD" | jq -r '
  "published \(.days|length) days for \(.org)",
  "  PRs opened    \(.pr_opened|add)",
  "  PRs merged    \(.pr_merged|add)",
  "  Issues opened \(.issues_opened|add)",
  "  Issues closed \(.issues_closed|add)"'
