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

# Cluster-aware kubeconfig. Running IN the cluster (a CronJob under the
# hive-ops ServiceAccount) there is no kubeconfig at all — kubectl must use the
# in-cluster service account. Defaulting KUBECONFIG to a workstation path there
# makes every kubectl call fail with a missing-file error that reads like the
# hive is down. Note `${VAR:=default}` fires on EMPTY as well as unset, so
# passing KUBECONFIG="" from a pod spec is not enough on its own.
if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

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

# GitHub credential: a fresh App INSTALLATION TOKEN, minted inside the hive pod.
#
# This replaced `gh api`. Two reasons, both of which bit us:
#   - `gh`'s token here is keyring-backed, and this runs unattended — the same
#     footgun hive-repo-sync.sh documents. In-cluster there is no `gh` at all.
#   - The App identity is the correct one for reading this org's issues; a
#     personal token is incidental and carries far wider scope.
# RS256 signing needs openssl, which the ops image lacks and the hive pod has —
# so the JWT is built there and only the short-lived token crosses back.
LABEL=app.kubernetes.io/name=hive
POD=$(kubectl get pods -n "$NS" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$POD" ] || { echo "ERROR: no hive pod found" >&2; exit 1; }

GH_TOKEN_VALUE=$(kubectl exec -n "$NS" "$POD" -- sh -c '
  APP_ID='"$(kubectl get secret -n "$NS" hive-secrets -o jsonpath='{.data.GH_APP_ID}' | base64 -d)"'
  INST_ID='"$(kubectl get secret -n "$NS" hive-secrets -o jsonpath='{.data.GH_APP_INSTALLATION_ID}' | base64 -d)"'
  PEM=/etc/hive-secrets/gh-app-key.pem
  [ -f "$PEM" ] || PEM=$(find / -maxdepth 4 -iname "gh-app-key.pem" 2>/dev/null | head -1)
  NOW=$(date +%s)
  B64() { openssl base64 -e -A | tr "+/" "-_" | tr -d "="; }
  H=$(printf "{\"alg\":\"RS256\",\"typ\":\"JWT\"}" | B64)
  P=$(printf "{\"iat\":%s,\"exp\":%s,\"iss\":\"%s\"}" "$((NOW-60))" "$((NOW+300))" "$APP_ID" | B64)
  S=$(printf "%s.%s" "$H" "$P" | openssl dgst -sha256 -sign "$PEM" | B64)
  curl -sS -X POST -H "Authorization: Bearer $H.$P.$S" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/app/installations/$INST_ID/access_tokens" | jq -r ".token // empty"
' 2>/dev/null)
[ -n "$GH_TOKEN_VALUE" ] || { echo "ERROR: could not mint a GitHub App installation token" >&2; exit 1; }

# count <extra-query> <field> <day>
# Search is REST here on purpose: `gh search`/`gh pr list` are GraphQL, and the
# GraphQL bucket is shared with everything else on this account — it was
# observed exhausted mid-session while REST still had its full 5000. REST also
# gives total_count directly.
# The search API allows 30 requests/MINUTE and this run needs 4 per day of
# history. An earlier version mapped any non-numeric response to 0, so once the
# limit was hit every remaining query silently became a zero and the collector
# published a 14-day series of zeros OVER real data. A rate-limited query is
# "ask again", never "there were none" — so retry on the limit, and if a query
# still cannot be answered, fail the whole run rather than publish a series with
# invented zeros in it.
count() {
  local extra="$1" field="$2" day="$3" q body n attempt=0
  q=$(printf 'org:%s author:%s %s %s:%s' "$ORG" "$BOT" "$extra" "$field" "$day" \
      | jq -sRr @uri)
  while [ "$attempt" -lt 4 ]; do
    body=$(curl -sS --max-time 25 \
           -H "Authorization: Bearer $GH_TOKEN_VALUE" \
           -H "Accept: application/vnd.github+json" \
           -H "User-Agent: hive-metrics" \
           "https://api.github.com/search/issues?q=$q&per_page=1" 2>/dev/null)
    n=$(printf '%s' "$body" | jq -r '.total_count // empty' 2>/dev/null)
    case "$n" in ''|*[!0-9]*) ;; *) echo "$n"; return 0 ;; esac
    # Secondary/primary rate limit, or a transient 5xx: wait out the window.
    case "$(printf '%s' "$body" | jq -r '.message // empty' 2>/dev/null)" in
      *[Rr]ate*|*abuse*|*secondary*) sleep 25 ;;
      *) sleep 5 ;;
    esac
    attempt=$((attempt + 1))
  done
  echo "ERROR: search failed for $field:$day ($extra) -> $(printf '%s' "$body" | head -c 160)" >&2
  return 1
}

days=""; pr_open=""; pr_merged=""; is_open=""; is_closed=""
i=$((DAYS - 1))
while [ "$i" -ge 0 ]; do
  # Portable date arithmetic. `date -d "-N day"` is GNU-only and `date -v` is
  # BSD-only; the in-cluster image ships BUSYBOX date, which has neither. Both
  # fell through to an EMPTY $d, which produced queries like `created:` — those
  # return 0 rather than erroring, so the collector cheerfully published a
  # 14-day series of zeros and overwrote real data. Fail loudly instead.
  d=$(python3 -c "
import datetime,sys
print((datetime.datetime.now(datetime.UTC)-datetime.timedelta(days=int(sys.argv[1]))).strftime('%Y-%m-%d'))" "$i" 2>/dev/null)
  [ -n "$d" ] || { echo "ERROR: could not compute a date for offset $i" >&2; exit 1; }
  days="$days,\"$d\""
  # A failed count aborts the run: a partial series published over a good one
  # is worse than no update at all.
  po=$(count 'type:pr' created "$d")            || exit 1
  pm=$(count 'type:pr is:merged' merged "$d")   || exit 1
  io=$(count 'type:issue' created "$d")         || exit 1
  ic=$(count 'type:issue is:closed' closed "$d") || exit 1
  pr_open="$pr_open,$po"; pr_merged="$pr_merged,$pm"
  is_open="$is_open,$io"; is_closed="$is_closed,$ic"
  # 4 requests per day of history against a 30/min ceiling: 9s per day keeps a
  # 14-day run comfortably inside the window even with the retry budget.
  sleep 9
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
