# shellcheck shell=bash
# hive-lib.sh — shared plumbing + pure decision helpers for the hive-ops scripts.
# SOURCED, never executed. Everything here is side-effect free at source time
# except hive_kube_env, which each script calls explicitly.
#
# WHY A LIBRARY (2026-09-24, after the v4 -> upstream v5 migration)
# ----------------------------------------------------------------
# Every script used to reach the dashboard API the same way: `kubectl exec
# <hive pod> -- curl http://127.0.0.1:3002/...`. Three things made that fall
# over at once:
#
#  1. v5's GET /api/status is ~3 MB (2.9 MB of it is `.repos`). Streamed back
#     through `kubectl exec` from the ops pod it took 24-26 s, and every script
#     passed `curl --max-time 20/25` — so about a third of reads came back
#     truncated and failed with "could not read /api/status -> {...".
#  2. kubectl 1.31 tries a WebSocket exec first. The hive-ops Role grants
#     `create` on pods/exec but not `get`, so the upgrade is refused (403) and
#     kubectl falls back to SPDY — every exec paid ~2 s for a failed handshake
#     before doing any work. KUBECTL_REMOTE_COMMAND_WEBSOCKETS=false skips it.
#  3. v5's switch/model/effort/restart endpoints restart the agent INSIDE the
#     request, so a mutation can legitimately take >25 s; a 25 s client
#     timeout reported them as failures ("jq: parse error" on "curl: (28)").
#
#  4. The hive node (ip-10-20-1-10, 4 vCPU, also the control plane) runs at a
#     load average of ~85-90. The ops jobs are pinned there (their state PVC
#     is local-path on that node), and under that run queue the kubectl BINARY
#     alone costs 8 s to start and every `kubectl get`/`exec` 10-35 s wall —
#     while a plain curl to the same API server answers in under a second.
#
# So: in-cluster, talk to the hive's own Service (http://hive.<ns>.svc:3002)
# with the owner session cookie, and to the Kubernetes API with curl + the
# ServiceAccount token (k8s_get/k8s_put_cm/k8s_scale) — kubectl only for
# `exec`, which has no curl equivalent. The session cookie is cached so a
# normal run needs no exec at all. /api/status is trimmed to the fields the
# scripts read. Outside the cluster (a workstation) Service DNS is not
# resolvable, so everything falls back to kubectl, and /api/status is trimmed
# INSIDE the pod with the pod's jq before anything crosses the exec stream.

HIVE_LABEL="${HIVE_LABEL:-app.kubernetes.io/name=hive}"
HIVE_API_PORT="${HIVE_API_PORT:-3002}"

# hive_kube_env: pick the kubeconfig. In-cluster (a CronJob under the hive-ops
# ServiceAccount) there is no kubeconfig at all and KUBECONFIG must be unset;
# `${VAR:=default}` fires on EMPTY as well as unset, so a pod spec passing
# KUBECONFIG="" is not enough on its own.
hive_kube_env() {
  if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
    : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
    export KUBECONFIG
  else
    unset KUBECONFIG
    export KUBECTL_REMOTE_COMMAND_WEBSOCKETS="${KUBECTL_REMOTE_COMMAND_WEBSOCKETS:-false}"
  fi
}

# hive_via: "svc" (direct HTTP to the Service) or "exec" (curl inside the pod).
hive_via() {
  if [ -n "${HIVE_API_VIA:-}" ]; then echo "$HIVE_API_VIA"
  elif [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then echo svc
  else echo exec
  fi
}

# ── Kubernetes API without kubectl (in-cluster) ─────────────────────────
_K8S_SA=/var/run/secrets/kubernetes.io/serviceaccount
_k8s_curl() {  # <METHOD> <path> [content-type] [body-file]
  curl -sS --fail-with-body --max-time "${HIVE_K8S_TIMEOUT:-30}" -X "$1" \
    --cacert "$_K8S_SA/ca.crt" -H "Authorization: Bearer $(cat "$_K8S_SA/token")" \
    ${3:+-H "Content-Type: $3"} ${4:+--data-binary "@$4"} \
    "https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT:-443}$2"
}
_k8s_direct() { [ -n "${KUBERNETES_SERVICE_HOST:-}" ] && [ -r "$_K8S_SA/token" ]; }

# k8s_get <api-path>: raw JSON GET.
k8s_get() {
  if _k8s_direct; then _k8s_curl GET "$1" 2>/dev/null
  else timeout "${HIVE_KUBECTL_TIMEOUT:-60}" kubectl get --raw "$1" 2>/dev/null
  fi
}

# k8s_put_cm <ns> <name> <data-json-object>: create or replace a ConfigMap's data.
k8s_put_cm() {
  local ns="$1" name="$2" data="$3" f rc
  if _k8s_direct; then
    f=$(mktemp)
    jq -n --arg ns "$ns" --arg n "$name" --argjson d "$data" \
      '{apiVersion:"v1",kind:"ConfigMap",metadata:{name:$n,namespace:$ns},data:$d}' > "$f"
    if _k8s_curl PUT "/api/v1/namespaces/$ns/configmaps/$name" application/json "$f" >/dev/null 2>&1 \
       || _k8s_curl POST "/api/v1/namespaces/$ns/configmaps" application/json "$f" >/dev/null 2>&1; then rc=0; else rc=1; fi
    rm -f "$f"; return $rc
  fi
  printf '%s' "$data" | jq -r 'to_entries[] | "--from-literal=\(.key)=\(.value)"' \
    | tr '\n' '\0' | xargs -0 kubectl create configmap "$name" -n "$ns" --dry-run=client -o yaml 2>/dev/null \
    | timeout "${HIVE_KUBECTL_TIMEOUT:-60}" kubectl apply -f - >/dev/null 2>&1
}

# k8s_scale <ns> <deployment> <replicas>
k8s_scale() {
  local f rc
  if _k8s_direct; then
    f=$(mktemp); printf '{"spec":{"replicas":%d}}' "$3" > "$f"
    _k8s_curl PATCH "/apis/apps/v1/namespaces/$1/deployments/$2/scale" application/merge-patch+json "$f" >/dev/null 2>&1; rc=$?
    rm -f "$f"; return $rc
  fi
  timeout "${HIVE_KUBECTL_TIMEOUT:-60}" kubectl scale deploy -n "$1" "$2" --replicas="$3" >/dev/null 2>&1
}

hive_pod() {
  k8s_get "/api/v1/namespaces/$1/pods?labelSelector=$(printf '%s' "$HIVE_LABEL" | sed 's|/|%2F|g; s|=|%3D|g')" \
    | jq -r '[.items[]? | select(.status.phase=="Running" and .metadata.deletionTimestamp == null)]
             | .[0].metadata.name // empty' 2>/dev/null
}

# hive_sid <ns> <pod>: newest owner session from the dashboard's own store
# (one exec). Deliberately NO local expiry comparison: the store writes the
# pod's UTC offset and a string compare against the caller's `date` is only
# accidentally right. The server is the authority.
hive_sid() {
  timeout "${HIVE_EXEC_TIMEOUT:-90}" kubectl exec -n "$1" "$2" -- \
      cat /data/dashboard-sessions.json 2>/dev/null \
    | jq -r 'to_entries | map(select(.value.Role=="owner"))
             | sort_by(.value.ExpiresAt) | reverse | .[0].key // empty' 2>/dev/null
}

# Session cache. Reading the store costs an exec (10-35 s on the loaded node)
# and sessions live for weeks, so the cookie is cached (mode 600, in the ops
# state volume, which only hive-ops jobs mount). A rejected cookie is dropped
# and re-read — see hive_open.
_sid_cache() {
  local d="${HIVE_SID_CACHE_DIR:-}"
  if [ -z "$d" ]; then
    if [ -d /state ] && [ -w /state ]; then d=/state/sessions; else d="$HOME/.local/state/hive-ops/sessions"; fi
  fi
  printf '%s/%s.sid' "$d" "$1"
}
hive_session() {  # <ns> <pod> [fresh]
  local f sid; f=$(_sid_cache "$1")
  if [ "${3:-}" != fresh ] && [ -s "$f" ]; then cat "$f"; return 0; fi
  sid=$(hive_sid "$1" "$2")
  [ -n "$sid" ] || return 1
  ( umask 077; mkdir -p "$(dirname "$f")" && printf '%s' "$sid" > "$f" ) 2>/dev/null
  printf '%s' "$sid"
}

# _hive_json_or_error: pass a JSON body through; wrap anything else (curl
# errors, HTML, empty) as {"ok":false,"error":...} so callers can always jq.
_hive_json_or_error() {
  local body="$1" rc="$2"
  if [ "$rc" = 0 ] && printf '%s' "$body" | jq -e . >/dev/null 2>&1; then
    printf '%s' "$body"
  else
    jq -cn --arg e "transport rc=$rc: $(printf '%s' "$body" | head -c 200)" '{ok:false,error:$e}'
  fi
}

# hive_call <ns> <pod> <sid> <METHOD> <path> [max_time] [json_body]
# Mutations default to 150 s: v5 restarts the agent inside switch/model/
# effort/restart requests. A json_body is sent as application/json (it is
# never a secret: backend/model/effort).
hive_call() {
  local ns="$1" pod="$2" sid="$3" method="$4" upath="$5" mt="${6:-}" data="${7:-}" body rc
  local -a extra=()
  [ -z "$mt" ] && { [ "$method" = GET ] && mt=60 || mt=150; }
  [ -n "$data" ] && extra=(-H "Content-Type: application/json" --data "$data")
  if [ "$(hive_via)" = svc ]; then
    body=$(curl -sS -X "$method" --max-time "$mt" -H "Cookie: hive_session=$sid" "${extra[@]}" \
             "http://hive.$ns.svc:$HIVE_API_PORT$upath" 2>&1); rc=$?
  else
    body=$(timeout $((mt + 30)) kubectl exec -n "$ns" "$pod" -- \
             curl -sS -X "$method" --max-time "$mt" -H "Cookie: hive_session=$sid" "${extra[@]}" \
             "http://127.0.0.1:$HIVE_API_PORT$upath" 2>&1); rc=$?
  fi
  _hive_json_or_error "$body" "$rc"
}

# hive_placement_body <backend> <model>: the JSON for the ATOMIC placement
# endpoint PUT /api/config/agent/{name}/models (v5.35, hivecommons/hive#7374):
# backend, model and — for agy only — the reasoning effort its suffixed model
# REQUIRES, all applied to the live launch config with ONE restart. The old
# /api/switch then /api/model pair restarted twice and, when the second call
# failed, left an unlaunchable pair (codex with a claude model; pi launched
# with a gemini id). agy needs the effort in the same request or v5 launches
# a -high model with `--effort low` (hivecommons/hive#8714). Other backends
# get no effort key: the field is validated per backend and "absent" means
# "leave unchanged".
hive_placement_body() {
  local b="$1" m="$2" e=""
  [ "$b" = agy ] && e=$(agy_effort_of "$m")
  jq -cn --arg b "$b" --arg m "$m" --arg e "$e" \
    '{backend: $b, model: $m} + (if $e != "" then {reasoning_effort: $e} else {} end)'
}

# hive_placement_ok <response>: 0 when the atomic endpoint confirmed it.
hive_placement_ok() {
  printf '%s' "$1" | jq -e '.ok == true and (if has("applied") then .applied == true else true end) and ((.status // "") | startswith("updated"))' >/dev/null 2>&1
}

# The fields any ops script reads. `liveSummary` is the hive's own last pane
# capture, which lets the watchdog classify panes without a tmux exec per agent.
# `.agents[]` (no `?`) on purpose: a refused cookie answers {"error":...}, and
# that must FAIL here (so hive_open re-reads the session) rather than become a
# successful-looking hive with zero agents.
HIVE_STATUS_SLIM_JQ='{
  timestamp, hiveId, acmmLevel,
  governorMode: (.governor.mode // .hiveAdvice.epoch.mode // null),
  budget: {BUDGET_EXHAUSTED: (.budget.BUDGET_EXHAUSTED // false),
           BUDGET_PCT_USED: (.budget.BUDGET_PCT_USED // 0),
           BUDGET_WEEKLY: (.budget.BUDGET_WEEKLY // 0)},
  agents: [ .agents[] | {name, cli, govModel, model, paused, pausedTrigger,
            pausedReason, onDemand, cadence, state, busy, enabled, needsLogin,
            authKnown, authAvailable,
            restarts, lastKick, structuredStatus, statusEvidence, kickOutcome,
            doing, liveSummary} ]
}'

# hive_status <ns> <pod> <sid>: slim /api/status JSON on stdout, rc 1 on failure
# (with the reason on stderr).
hive_status() {
  local ns="$1" pod="$2" sid="$3" out rc
  if [ "$(hive_via)" = svc ]; then
    out=$(curl -sS --max-time "${HIVE_STATUS_TIMEOUT:-90}" -H "Cookie: hive_session=$sid" \
            "http://hive.$ns.svc:$HIVE_API_PORT/api/status" 2>&1 \
          | jq -c "$HIVE_STATUS_SLIM_JQ" 2>&1); rc=$?
  else
    # Trim inside the pod: only ~50 KB crosses the exec stream instead of 3 MB.
    # Arguments go positionally to `sh -c`, never interpolated into the script.
    # shellcheck disable=SC2016
    out=$(timeout $(( ${HIVE_STATUS_TIMEOUT:-90} + 30 )) kubectl exec -n "$ns" "$pod" -- sh -c '
        curl -sS --max-time "$1" -H "Cookie: hive_session=$2" \
          "http://127.0.0.1:$3/api/status" | jq -c "$4"' \
        sh "${HIVE_STATUS_TIMEOUT:-90}" "$sid" "$HIVE_API_PORT" "$HIVE_STATUS_SLIM_JQ" 2>&1); rc=$?
  fi
  if [ "$rc" = 0 ] && printf '%s' "$out" | jq -e '.agents | type == "array"' >/dev/null 2>&1; then
    printf '%s' "$out"
    return 0
  fi
  echo "hive_status($ns): rc=$rc ${out:0:200}" >&2
  return 1
}

# hive_open <ns>: resolve POD, SID and STATUS_JSON (globals) for one hive,
# retrying once with a freshly read session when the cached cookie is refused.
# Returns 1 with a reason on stderr when the hive cannot be read.
# shellcheck disable=SC2034  # POD/SID/STATUS_JSON are this function's outputs
hive_open() {
  POD=$(hive_pod "$1")
  [ -n "$POD" ] || { echo "no running hive pod in $1" >&2; return 1; }
  SID=$(hive_session "$1" "$POD") \
    || { echo "no owner session in $1's session store — log in to that dashboard" >&2; return 1; }
  if STATUS_JSON=$(hive_status "$1" "$POD" "$SID"); then return 0; fi
  SID=$(hive_session "$1" "$POD" fresh) || return 1
  STATUS_JSON=$(hive_status "$1" "$POD" "$SID")
}

# ── Pure helpers (unit-tested in tests/test_hive_ops_lib.py) ──────────────

# hive_provider_of <backend> <model>: the ACCOUNT an agent draws on.
# CLI wins for backends whose auth is tied to the CLI (copilot, muse); then a
# pi provider prefix (`kiro-api-key/claude-sonnet-5` bills the KIRO account,
# not Anthropic — the prefix must win over sniffing the model family); then
# model-name sniffing; then the CLI's own default provider.
#
# `pi`/`goose` with no recognisable model now map to `unknown`: they used to
# default to deepseek, which the fleet no longer uses (2026-09-24, the owner is
# not topping it up). A legacy `deepseek-*` model still sniffs as deepseek so
# rotation can see it and move the agent off.
hive_provider_of() {
  local c m
  c=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]'); m=$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')
  case "$c" in copilot) echo github; return;; muse) echo meta; return;; esac
  case "$m" in kiro-api-key/*|kiro/*) echo kiro; return;; esac
  case "$m" in *deepseek*) echo deepseek; return;; *claude*|*opus*|*sonnet*|*haiku*|*fable*) echo anthropic; return;;
               *gpt-*|*codex*) echo openai; return;; *gemini*) echo google; return;; esac
  case "$c" in claude|litellm) echo anthropic;; codex) echo openai;; agy) echo google;;
               bob) echo ibm;; *) echo unknown;; esac
}

# hive_model_path <model>: a model id as ONE URL path segment. Kiro ids carry
# the pi provider prefix (`kiro-api-key/claude-sonnet-5`); v5 routes
# POST /api/model/{agent}/{model}, so an unescaped `/` would 404.
hive_model_path() { printf '%s' "$1" | sed 's|/|%2F|g'; }

# agy_effort_of <model>: the --effort an agy model id REQUIRES.
# v5 launches agy as `--model <m> --effort <agent effort, default low>`, and
# agy refuses a suffixed id whose suffix disagrees with --effort:
#   "--model gemini-3.8-flash-high conflicts with --effort=low.
#    Using "Gemini 3.6 Flash (Low)" instead."
# i.e. every T1 `-high` rung was silently running the cheapest Gemini.
agy_effort_of() {
  case "$1" in
    *-high)   echo high ;;
    *-medium) echo medium ;;
    *-low)    echo low ;;
    *)        echo "" ;;
  esac
}

# effort_change <backend> <model> <recorded-effort>: prints the effort to set,
# or nothing when none is needed. <recorded-effort> is what we last set for
# this agent ("" = never set, which on v5 means agy's default, low).
effort_change() {
  local b="$1" m="$2" rec="${3:-}" want
  [ "$b" = agy ] || return 0
  want=$(agy_effort_of "$m")
  [ -n "$want" ] || return 0
  [ -z "$rec" ] && rec=low
  [ "$want" = "$rec" ] || echo "$want"
}

# watchdog_backoff_s <heal-count>: seconds to wait before healing again.
# Exponential (the CrashLoopBackOff analog the watchdog always claimed to be):
# base, 2x, 4x ... capped. The old fixed 5-minute interval restarted a
# permanently-broken agent 288 times a day, and v5 counts those restarts into
# its own crash-loop breaker (`BLOCKED: crash-looping (N restarts in 24h)`).
watchdog_backoff_s() {
  local n="${1:-0}" base="${HIVE_WATCHDOG_BASE_MIN:-5}" cap="${HIVE_WATCHDOG_MAX_MIN:-120}" m
  [ "$n" -lt 1 ] 2>/dev/null && { echo 0; return; }
  m=$base
  while [ "$n" -gt 1 ] && [ "$m" -lt "$cap" ]; do m=$((m * 2)); n=$((n - 1)); done
  [ "$m" -gt "$cap" ] && m=$cap
  echo $((m * 60))
}

# pane_classify_text: classify a captured pane (stdin) as
# ready|wizard|auth|approval|shell|empty. Patterns are anchored to CLI CHROME, never
# loose English an agent might be reading in an issue body.
pane_classify_text() {
  local text last
  text=$(cat)
  [ -z "$(printf '%s' "$text" | grep -v '^[[:space:]]*$')" ] && { echo empty; return; }
  # First-run wizards (agy theme/ToS, workspace trust prompts incl. muse's) are
  # DIALOGS caused by shared-home permission drift — repair + relaunch in
  # place, never rotate off a healthy provider over one.
  if printf '%s' "$text" | grep -qiE '\[next\]|\[previous\]|terms of service & data use|accent: highlighted|enter toggl|choose your color scheme|do you trust the contents|do you trust this workspace|i trust this folder|welcome to (the )?antigravity'; then
    echo wizard; return
  fi
  if printf '%s' "$text" | grep -qiE 'login expired|run /login|not logged in|please run /login|please use /login|select login method|sign in to use copilot|paste code here if prompted|browser didn.t open\? use the url below'; then
    echo auth; return
  fi
  # muse parked on a tool-approval prompt. v5.35 launches hosted muse with NO
  # flags (manager_launch has no muse case), i.e. --approval-mode on-request
  # plus the LLM approval judge, and the judge escalates commands that read
  # the environment (`env | grep GH_…`) to a human who never comes. Observed
  # 2026-09-24: reef/outreach and hanthor/guide sat 38-53 min on it. Restarting
  # re-asks the same question, so the watchdog treats it like `auth`: rotate
  # the agent off the backend. Anchored to muse's own menu chrome.
  if printf '%s' "$text" | grep -qE 'Would you like to run the following command\?' &&
     printf '%s' "$text" | grep -qE 'Yes, proceed \(y\)'; then
    echo approval; return
  fi
  last=$(printf '%s\n' "$text" | grep -v '^[[:space:]]*$' | tail -1 | sed 's/[[:space:]]*$//')
  # A shell prompt as the LAST line = the CLI exited to bash. The agents'
  # prompts are `hive-<agent>@<pod>:<path>$`; a trailing command after it is
  # a launch line the CLI never drew over (it died during startup).
  case "$last" in
    *'$'|*'#') echo shell; return ;;
    hive-*@*:*'$ '*) echo shell; return ;;
  esac
  echo ready
}

# published_to_probe "<value>": convert a hive-provider-usage ConfigMap value
# ("37% used resets=..." / "unknown no-agent") back to "<pct> <note>".
published_to_probe() {
  local v="$1" pct note
  case "$v" in
    unknown*) note=${v#unknown}; note=${note# }; echo "-1 ${note:-unpublished}" ;;
    [0-9]*"% used"*) pct=${v%%%*}; note=${v#*% used}; note=${note# }; echo "$pct $note" ;;
    *) echo "-1 unpublished" ;;
  esac
}

# rung_down <model>: the pacer's one-notch-cheaper rung on the SAME provider
# and backend, or nothing. Shared by hive-pace (demote) and hive-rotate (which
# must treat a pacer-demoted rung as legitimate, or the two fight).
rung_down() {
  case "$1" in
    claude-fable-5-1|claude-fable-5|claude-opus-5-5|claude-opus-5) echo claude-sonnet-5 ;;
    gemini-3.8-flash-high)  echo gemini-3.8-flash-low ;;
    gemini-3.7-flash-high)  echo gemini-3.7-flash-low ;;
    gpt-6-astra|gpt-5.6-sol) echo gpt-5.6-luna ;;
    # Kiro credits scale with the model's rateMultiplier (ListAvailableModels,
    # 2026-09-24): opus-5 2.2, sonnet-5 1.3, gpt-5.6 sol 4.4 / terra 2.2 /
    # luna 1.1. Demote to the cheaper model of the same family; the pi
    # `:<thinking>` suffix (see hive-rotate.sh TIERS) is kept as is.
    kiro-api-key/claude-opus-5|kiro-api-key/claude-opus-5:*)
      echo "kiro-api-key/claude-sonnet-5${1#kiro-api-key/claude-opus-5}" ;;
    kiro-api-key/gpt-5-6-sol|kiro-api-key/gpt-5-6-sol:*)
      echo "kiro-api-key/gpt-5-6-luna${1#kiro-api-key/gpt-5-6-sol}" ;;
    kiro-api-key/gpt-5-6-terra|kiro-api-key/gpt-5-6-terra:*)
      echo "kiro-api-key/gpt-5-6-luna${1#kiro-api-key/gpt-5-6-terra}" ;;
    # Second notch (2026-09-25, Kiro budget pacing): sonnet-5 1.3 / luna 1.1
    # -> haiku-4.5 0.4, the bottom of the Kiro ladder. Always `:low` — the
    # exact T3 rung (launch-verified under pi), whatever the upper suffix was.
    kiro-api-key/claude-sonnet-5|kiro-api-key/claude-sonnet-5:*|kiro-api-key/gpt-5-6-luna|kiro-api-key/gpt-5-6-luna:*)
      echo "kiro-api-key/claude-haiku-4-5:low" ;;
    *)                      echo "" ;;
  esac
}

# rung_chain <model>: the model, then every rung_down below it (one per line).
rung_chain() {
  local m="$1" i=0
  while [ -n "$m" ] && [ "$i" -lt 6 ]; do echo "$m"; m=$(rung_down "$m"); i=$((i + 1)); done
}

# rung_up_toward <original> <current>: the rung one notch ABOVE <current> on
# <original>'s demotion chain (== <original> after the first notch), or
# nothing when <current> is not below <original> on that chain.
rung_up_toward() {
  local prev="" m
  while IFS= read -r m; do
    [ "$m" = "$2" ] && { [ -n "$prev" ] && echo "$prev"; return 0; }
    prev=$m
  done <<< "$(rung_chain "$1")"
  return 0
}

# kiro_credit_mult <model>: Kiro credits per request (rateMultiplier from
# ListAvailableModels, 2026-09-24). Unknown kiro models count as 1.0.
kiro_credit_mult() {
  case "$1" in
    *gpt-5-6-sol*)   echo 4.4 ;;
    *gpt-5-6-terra*) echo 2.2 ;;
    *gpt-5-6-luna*)  echo 1.1 ;;
    *claude-opus-*)  echo 2.2 ;;
    *claude-sonnet-*) echo 1.3 ;;
    *claude-haiku-*) echo 0.4 ;;
    *)               echo 1.0 ;;
  esac
}

# pace_demoted_from <demoted-file> <ns> <agent> <current-model>: when the
# pacer demoted this agent and it is still sitting on a rung of that demotion
# chain, print the ORIGINAL "backend|model" it was demoted from; else nothing.
pace_demoted_from() {
  local f="$1" key="$2/$3" cur="$4" line ob om
  [ -s "$f" ] || return 0
  line=$(grep -F "$key|" "$f" 2>/dev/null | tail -1)
  [ -n "$line" ] || return 0
  ob=$(printf '%s' "$line" | cut -d'|' -f2); om=$(printf '%s' "$line" | cut -d'|' -f3)
  # Any notch BELOW the original counts (the Kiro ladder has two:
  # opus -> sonnet -> haiku). The row keeps the ORIGINAL rung however many
  # notches the pacer has taken, so rotate still sees the tier it came from.
  rung_chain "$om" | tail -n +2 | grep -qxF -- "$cur" && echo "$ob|$om"
  return 0
}

# pane_stalled <state-file> <busy> <pane-text> <now-epoch> [minutes]
# 0 (stalled) when a turn is still open (busy=working) and the pane has been
# byte-identical for at least <minutes> (default HIVE_WATCHDOG_STALL_MIN, 60).
# Records "<hash> <first-seen>" in <state-file>; an idle agent clears it.
#
# Why: v5 marks an agent `working` until it sees the kicked turn END. An agent
# whose CLI swallowed the prompt (school/architect sat 7 h on a pasted kick
# prompt; v5 itself logged "CLI did not reach input prompt") matches no chrome
# pattern, so pane_classify_text calls it `ready` and nothing ever healed it,
# while the governor kept waiting on a turn that would never end. A live turn
# changes the pane (tool output, spinners, timers); an hour of identical bytes
# is a hang.
pane_stalled() {
  local f="$1" busy="$2" text="$3" now="$4" min="${5:-${HIVE_WATCHDOG_STALL_MIN:-60}}" h ph pf
  if [ "$busy" != working ]; then rm -f "$f" 2>/dev/null; return 1; fi
  h=$(printf '%s' "$text" | md5sum | cut -c1-16)
  { read -r ph pf < "$f"; } 2>/dev/null || { ph=""; pf=""; }
  if [ "$h" != "$ph" ] || [ -z "$pf" ]; then
    echo "$h $now" > "$f" 2>/dev/null
    return 1
  fi
  [ $(( now - pf )) -ge $(( min * 60 )) ]
}

# ── Provider readings from ccleft (2026-09-25) ────────────────────────────
# ccleft (talos-k8s/hive/ccleft) is the ONE poller of every provider's quota
# endpoint: single-flight, per-provider min interval, backoff on 429, and a
# last-good reading marked stale:true. The ops scripts used to poll the same
# accounts themselves (rotate's probe_all), and because busybox `date` cannot
# parse the ISO timestamps the "reuse a fresh publication" path always failed,
# so every rotate AND every watchdog (3 hives x every 5 min) hit Anthropic's
# OAuth usage endpoint — which then 429'd ccleft's own calls.
#
# HIVE_PROBE_SOURCE=ccleft (default) reads GET /readings and translates each
# reading into the exact "<pct_used> <note>" the direct parsers produce, so
# every decision downstream is unchanged. HIVE_PROBE_SOURCE=direct, or ccleft
# being unreachable, uses the old direct probes (kept, logged loudly).
HIVE_CCLEFT_DEFAULT_URL="http://ccleft.hive.svc:9464"

hive_probe_source() {
  case "${HIVE_PROBE_SOURCE:-ccleft}" in direct) echo direct ;; *) echo ccleft ;; esac
}

# iso_to_epoch <ISO-8601>: epoch seconds, or nothing. jq, not `date -d`: the
# ops image's busybox date rejects "2026-09-25T13:40:20Z" (that bug silently
# disabled published-usage reuse and the renewal wake-up).
iso_to_epoch() {
  jq -rn --arg t "$1" 'try ($t | sub("\\.[0-9]+"; "") | sub("(\\+00:00|\\+0000)$"; "Z") | fromdateiso8601) catch empty' 2>/dev/null
}

# ccleft_fetch: the /readings JSON on stdout; rc 1 (reason on stderr) when
# ccleft cannot be read. In-cluster (or with HIVE_CCLEFT_URL set) over the
# Service; from a workstation through `kubectl exec deploy/ccleft`.
ccleft_fetch() {
  local body rc
  if [ -n "${HIVE_CCLEFT_URL:-}" ] || [ -n "${KUBERNETES_SERVICE_HOST:-}" ]; then
    body=$(curl -sS --max-time "${HIVE_CCLEFT_TIMEOUT:-15}" "${HIVE_CCLEFT_URL:-$HIVE_CCLEFT_DEFAULT_URL}/readings" 2>&1); rc=$?
  else
    body=$(timeout "${HIVE_KUBECTL_TIMEOUT:-60}" kubectl -n "${HIVE_CCLEFT_NS:-hive}" exec deploy/ccleft -- \
             curl -sS --max-time "${HIVE_CCLEFT_TIMEOUT:-15}" http://127.0.0.1:9464/readings 2>&1); rc=$?
  fi
  if [ "$rc" = 0 ] && printf '%s' "$body" | jq -e '(.readings | type) == "array" and (.readings | length) > 0' >/dev/null 2>&1; then
    printf '%s' "$body"; return 0
  fi
  echo "ccleft unreadable (rc=$rc): $(printf '%s' "$body" | head -c 200)" >&2
  return 1
}

# The hive-ops provider pool -> ccleft's provider name.
ccleft_provider_name() {
  case "$1" in
    anthropic) echo claude ;; openai) echo codex ;; google) echo agy ;;
    meta) echo muse ;; github) echo copilot ;; *) echo "$1" ;;
  esac
}

# Shared jq definitions. A reading is USABLE when it has a fetched_at and is
# not too old: a stale (last-good) reading counts for $maxstale seconds, a
# fresh one for $maxfresh (a wedged ccleft must not serve yesterday forever).
# shellcheck disable=SC2016
_CCLEFT_JQ_DEFS='
def ep: sub("\\.[0-9]+"; "") | sub("(\\+00:00|\\+0000)$"; "Z") | fromdateiso8601;
def sec: sub("\\.[0-9]+"; "") | sub("(\\+00:00|\\+0000)$"; "Z");
def reading($cp): [.readings[]? | select(.provider == $cp)]
                  | sort_by(-((.homes // []) | length)) | first;
def age: if .fetched_at then ($now - (.fetched_at | ep)) else null end;
def usable: age as $a | $a != null
            and (if .stale == true then $a <= $maxstale else $a <= $maxfresh end);
def pctwins: [.windows[]? | select(.unit == "percent" and .used_pct != null)];
def upct: [[(.used_pct | ceil), 0] | max, 100] | min;
'

# ccleft_probe <hive-provider> [now-epoch]: stdin /readings JSON; prints
# "<pct_used> <note>" exactly like the parse_probe_* functions:
#   ok/limited with windows -> the worst binding window, as the direct probe
#                              collapsed it (anthropic: unscoped limits only;
#                              google: the Gemini windows only; kiro: the
#                              exact credit count in the note)
#   limited/exhausted, no window  -> 100
#   auth_required                 -> 100 no-credential (like an empty token)
#   unsupported                   -> -1 no-usage-api (entry allowed, as muse today)
#   error/rate_limited, no window -> -1 (unmeasured: never "exhausted")
#   stale older than HIVE_CCLEFT_MAX_STALE_S (1800) or absent -> -1 (unmeasured)
ccleft_probe() {
  local p="$1" now="${2:-$(date -u +%s)}"
  jq -r --arg cp "$(ccleft_provider_name "$p")" --arg p "$p" --argjson now "$now" \
     --argjson maxstale "${HIVE_CCLEFT_MAX_STALE_S:-1800}" \
     --argjson maxfresh "${HIVE_CCLEFT_MAX_AGE_S:-3600}" "$_CCLEFT_JQ_DEFS"'
    reading($cp) as $r
    | if $r == null then "-1 ccleft-no-reading"
      else ($r | age) as $age | ($r.cause // "") as $cause
      | (if $cause != "" then " cause=\($cause)" else "" end) as $cn
      | (if $r.stale == true then " (ccleft stale \($age / 60 | floor)m\($cn))" else "" end) as $st
      | if $age == null then "-1 ccleft-unmeasured state=\($r.state // "?")"
        elif ($r | usable | not) then "-1 ccleft-stale age=\($age / 60 | floor)m\($cn)"
        elif $r.state == "unsupported" then "-1 no-usage-api (ccleft unsupported\($cn))"
        elif $r.state == "auth_required" then "100 no-credential (ccleft auth_required\($cn): needs an interactive login)"
        else
          ( if $p == "kiro" then
              ([$r.windows[]? | select(.unit == "credits" and (.limit // 0) > 0)] | first) as $w
              | if $w == null then null else
                  { pct: ([(($w.used / $w.limit * 100) | floor), 100] | min),
                    note: ("credits=\(($w.used * 100 | round) / 100)/\($w.limit) resets=\($w.resets_at | sec)") }
                end
            else
              ($r | pctwins) as $all
              | (if $p == "anthropic" then [$all[] | select(.scope == null)]
                 elif $p == "google" then ([$all[] | select(.scope == "gemini")] | if length > 0 then . else $all end)
                 else $all end) as $ws
              | if ($ws | length) == 0 then null else
                  ($ws | max_by(.used_pct)) as $b
                  | { pct: ($b | upct),
                      note: ( (if $p == "openai" then
                                 ($ws | map((if .kind == "five_hour" then "5h" else (.kind // .id) end)
                                            + "=\(upct)%") | join(" ")) + " "
                               else "" end)
                              + (if $b.resets_at then "resets=\($b.resets_at | sec)" else "" end)
                              + (if $p == "anthropic" then
                                   ([$all[] | select(.scope != null and .used_pct >= 100) | .scope] | join(","))
                                   | if . != "" then " capped-models=\(.)" else "" end
                                 else "" end) ) }
                end
            end ) as $m
          | if $m != null then
              (if ($r.state == "exhausted" or $r.state == "limited") and $m.pct < 100
               then "100" else "\($m.pct)" end) + " " + ($m.note | ltrimstr(" ")) + $st
            elif $r.state == "exhausted" or $r.state == "limited" then
              "100 ccleft \($r.state)\($cn)" + (if $r.message then ": \($r.message | .[0:80])" else "" end)
            else "-1 ccleft-\($r.state // "unknown")\($cn)" end
        end
      end' 2>/dev/null | head -1 | grep . || echo "-1 ccleft-unparsed"
}

# ccleft_anthropic_limits [now-epoch]: stdin /readings; the unscoped Claude
# limits as the pacer's anthropic_limits array ([{slot,percent,resets_at}],
# sorted by reset so slot indexes are stable), or nothing when the Claude
# reading is not usable.
ccleft_anthropic_limits() {
  jq -c --argjson now "${1:-$(date -u +%s)}" \
     --argjson maxstale "${HIVE_CCLEFT_MAX_STALE_S:-1800}" \
     --argjson maxfresh "${HIVE_CCLEFT_MAX_AGE_S:-3600}" "$_CCLEFT_JQ_DEFS"'
    reading("claude") as $r
    | if $r == null or ($r | usable | not) then empty else
        [$r | pctwins[] | select(.scope == null and .resets_at != null)]
        | sort_by(.resets_at | ep)
        | to_entries | map({slot: "slot\(.key)", percent: (.value | upct), resets_at: (.value.resets_at | sec)})
        | if length == 0 then empty else . end
      end' 2>/dev/null
}

# ccleft_measured_at <hive-provider>: stdin /readings; epoch of that
# provider's reading (its fetched_at), or nothing.
ccleft_measured_at() {
  jq -r --arg cp "$(ccleft_provider_name "$1")" --argjson now 0 --argjson maxstale 0 --argjson maxfresh 0 \
     "$_CCLEFT_JQ_DEFS"'reading($cp) | if . == null or .fetched_at == null then empty else (.fetched_at | ep) end' 2>/dev/null
}

# ccleft_kiro_sample [now-epoch]: stdin /readings; one pace-history row for the
# Kiro credit pool, stamped with ccleft's FETCH time (not the caller's clock,
# so a reading seen by several jobs is one sample), or nothing.
ccleft_kiro_sample() {
  jq -c --argjson now "${1:-$(date -u +%s)}" \
     --argjson maxstale "${HIVE_CCLEFT_MAX_STALE_S:-1800}" \
     --argjson maxfresh "${HIVE_CCLEFT_MAX_AGE_S:-3600}" "$_CCLEFT_JQ_DEFS"'
    reading("kiro") as $r
    | if $r == null or ($r | usable | not) then empty else
        ([$r.windows[]? | select(.unit == "credits" and (.limit // 0) > 0)] | first) as $w
        | if $w == null then empty else
            {ts: ($r.fetched_at | ep), provider: "kiro", slot: "slot0",
             pct: (($w.used / $w.limit * 100000 | round) / 1000),
             reset: (if $w.resets_at then ($w.resets_at | ep) else null end),
             used: (($w.used * 100 | round) / 100), limit: $w.limit}
          end
      end' 2>/dev/null
}

# pace_history_add <history-file> <row-json>: append a sample unless a row for
# the same provider/slot/ts is already there (several jobs see one reading).
pace_history_add() {
  local f="$1" row="$2" key
  [ -n "$row" ] || return 0
  key=$(printf '%s' "$row" | jq -r '"\"ts\":\(.ts),\"provider\":\"\(.provider)\",\"slot\":\"\(.slot)\""' 2>/dev/null) || return 0
  [ -n "$key" ] || return 0
  tail -n 400 "$f" 2>/dev/null | grep -qF -- "$key" && return 0
  printf '%s\n' "$row" >> "$f"
}

# kiro_evict_targets <evict-file> <ns> <agent> [now-epoch]: when hive-pace has
# asked for this agent to leave Kiro (budget cap, see hive-pace.sh) and the
# request has not expired, print the target pools it judged to have headroom
# (space-separated); else nothing. Row: "<ns>/<agent>|<expiry-epoch>|<p1,p2>".
kiro_evict_targets() {
  local f="$1" key="$2/$3" now="${4:-$(date -u +%s)}" line exp tg
  [ -s "$f" ] || return 0
  line=$(grep -F "$key|" "$f" 2>/dev/null | tail -1)
  [ -n "$line" ] || return 0
  exp=$(printf '%s' "$line" | cut -d'|' -f2); tg=$(printf '%s' "$line" | cut -d'|' -f3)
  [ "${exp:-0}" -gt "$now" ] 2>/dev/null || return 0
  printf '%s' "$tg" | tr ',' ' '
}
