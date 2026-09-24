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

# hive_call <ns> <pod> <sid> <METHOD> <path> [max_time]
# Mutations default to 150 s: v5 restarts the agent inside switch/model/
# effort/restart requests.
hive_call() {
  local ns="$1" pod="$2" sid="$3" method="$4" upath="$5" mt="${6:-}" body rc
  [ -z "$mt" ] && { [ "$method" = GET ] && mt=60 || mt=150; }
  if [ "$(hive_via)" = svc ]; then
    body=$(curl -sS -X "$method" --max-time "$mt" -H "Cookie: hive_session=$sid" \
             "http://hive.$ns.svc:$HIVE_API_PORT$upath" 2>&1); rc=$?
  else
    body=$(timeout $((mt + 30)) kubectl exec -n "$ns" "$pod" -- \
             curl -sS -X "$method" --max-time "$mt" -H "Cookie: hive_session=$sid" \
             "http://127.0.0.1:$HIVE_API_PORT$upath" 2>&1); rc=$?
  fi
  _hive_json_or_error "$body" "$rc"
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
# ready|wizard|auth|shell|empty. Patterns are anchored to CLI CHROME, never
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
    *)                      echo "" ;;
  esac
}

# pace_demoted_from <demoted-file> <ns> <agent> <current-model>: when the
# pacer demoted this agent and it is still sitting on exactly that cheaper
# rung, print the "backend|model" it was demoted FROM; else nothing.
pace_demoted_from() {
  local f="$1" key="$2/$3" cur="$4" line ob om
  [ -s "$f" ] || return 0
  line=$(grep -F "$key|" "$f" 2>/dev/null | tail -1)
  [ -n "$line" ] || return 0
  ob=$(printf '%s' "$line" | cut -d'|' -f2); om=$(printf '%s' "$line" | cut -d'|' -f3)
  [ "$(rung_down "$om")" = "$cur" ] && echo "$ob|$om"
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
