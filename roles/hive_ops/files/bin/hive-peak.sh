#!/usr/bin/env bash
# Pause/resume tuna-os Hive agents during DeepSeek peak pricing windows.
# Peak hours (UTC): 01:00-04:00 and 06:00-10:00, WEEKDAYS ONLY since
# DeepSeek's 2026-08-23 policy change (weekends, Sat-Sun Beijing time, are
# all-day off-peak) — see hive-peak-pause.timer / hive-peak-resume.timer.
# Mirrors pi-peak-stop/start.service for the pi contributor (pi.container).
#
# Agents are paused via the dashboard API (POST /api/pause|resume/<agent>)
# run through kubectl exec on the pod. The pod stays up and serves the
# dashboard; only the agents stop consuming tokens.
#
# ── Auth: an owner SESSION cookie, not Bearer, not a token header ───────
# This spoke runs direct-route authz (see the `dashboard:` block in
# hive.yaml): standalone public spoke, no hub nginx in front. Therefore:
#
#   Authorization: Bearer          -> rejected outright
#   X-Hive-User / X-Hive-Role      -> rejected as forgeries (both tested)
#   X-Hive-Internal: <token>       -> authenticates, but READ-ONLY.
#                                     POSTs return "owner access required".
#   Cookie: hive_session=<sid>     -> full owner access. This is the one.
#
# The previous version of this script sent Bearer and enumerated agents from
# the HOST over the pod IP. Both are rejected, so every run since that authz
# change died at "ERROR: could not list agents from dashboard" and NO PEAK
# PAUSE EVER HAPPENED. Verified in the journal for both units.
#
# Note the cookie name is `hive_session` (underscore). `hive-session-v1`
# appears in the binary but is NOT the cookie name and returns unauthorized.
#
# The session id is read at runtime from the dashboard's own persisted session
# store inside the pod, selecting a non-expired owner session. That means a
# fresh browser login by an authorized_users member is picked up automatically
# with no edit here — and when every session has expired the script says so
# loudly instead of silently doing nothing, which is the failure mode that hid
# the previous breakage for weeks.
#
# Every call goes through kubectl exec: the request must originate inside the
# pod, so a host-side curl cannot work regardless of credentials.
#
# ── only DeepSeek agents are paused ─────────────────────────────────────
# The window exists for DeepSeek peak pricing, so it only touches agents
# actually spending DeepSeek credit. Once an agent is rotated onto Claude or
# OpenAI it is unaffected by DeepSeek's rates, and pausing it would throw away
# fleet capacity for no saving. Classification is by PROVIDER (see provider()
# below), not backend name, because `pi`/`goose` are shells over a configured
# provider and `claude`/`litellm` can share one Anthropic pool.
# Override the set of affected providers with HIVE_PEAK_PROVIDERS.
#
# ── resume only un-pauses what WE paused ────────────────────────────────
# Agents also get paused by other things — most commonly the login-detector
# ("login required detected"). Blanket-resuming would silently clear those
# and mask a real problem. So pause records the set it acted on, and resume
# restores only that set. Same contract as the dashboard's own fleet breaker
# ("Releasing restores only the agents this breaker paused").


# Hive runs on the AWS Talos cluster; override to point elsewhere.
: "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
export KUBECONFIG

set -u

STATE="${HIVE_PEAK_STATE:-$HOME/.local/state/hive-peak-paused}"

ACTION="${1:-}"
case "$ACTION" in
  pause|resume|status) ;;
  *) echo "usage: $0 pause|resume|status" >&2; exit 2 ;;
esac

NS=hive
LABEL=app.kubernetes.io/name=hive
API=http://127.0.0.1:3002   # dashboard port inside the pod

POD=$(kubectl get pods -n "$NS" -l "$LABEL" \
      -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$POD" ] || { echo "ERROR: no hive pod found" >&2; exit 1; }

# Newest non-expired owner session from the dashboard's own store. Expiry is
# compared as an ISO-8601 string against `date -Is`, which sorts correctly.
NOW=$(date -Is)
SID=$(kubectl exec -n "$NS" "$POD" -- \
        cat /data/dashboard-sessions.json 2>/dev/null \
      | jq -r --arg now "$NOW" '
          to_entries
          | map(select(.value.Role == "owner" and .value.ExpiresAt > $now))
          | sort_by(.value.ExpiresAt) | reverse | .[0].key // empty' 2>/dev/null)

if [ -z "$SID" ]; then
  echo "ERROR: no unexpired owner session in the hive dashboard session store." >&2
  echo "       Log in at https://hive.tunaos.org as an authorized_users member" >&2
  echo "       (GitHub device flow), then re-run. Mutations require an owner" >&2
  echo "       session; Bearer and X-Hive-Internal are read-only here." >&2
  exit 1
fi

# hive_api <method> <path> — always from inside the pod, always the session
# cookie. curl is passed straight to kubectl exec rather than wrapped in
# `sh -c` with an interpolated secret, which has produced bogus responses
# (see tunaos-hive-checkin).
hive_api() {
  kubectl exec -n "$NS" "$POD" -- \
    curl -sS -X "$1" --max-time 20 -H "Cookie: hive_session=$SID" "$API$2" 2>&1
}

STATUS_JSON=$(hive_api GET /api/status)
if ! printf '%s' "$STATUS_JSON" | jq -e '.agents' >/dev/null 2>&1; then
  echo "ERROR: could not list agents from dashboard -> ${STATUS_JSON:0:200}" >&2
  exit 1
fi

# ── Provider classification ─────────────────────────────────────────────
# This window exists for DEEPSEEK peak pricing, so it must only touch agents
# actually spending DeepSeek credit. An agent rotated onto Claude or OpenAI is
# unaffected by DeepSeek's peak rate and pausing it just burns fleet capacity
# for nothing.
#
# Classification keys on PROVIDER, not backend name: `pi` is a shell over
# PI_PROVIDER and `goose` over GOOSE_PROVIDER (both point at DeepSeek in this
# pod), while `claude` and `litellm` can share one Anthropic pool. The model
# name is the strongest signal, so it is tested first; the CLI name is only a
# fallback for when the model is unset.
PROVIDER_JQ='
def provider:
  ((.govModel // "") | ascii_downcase) as $m |
  ((.cli // "")      | ascii_downcase) as $c |
  if   ($m | test("deepseek"))                    then "deepseek"
  elif ($m | test("claude|opus|sonnet|haiku"))    then "anthropic"
  elif ($m | test("gpt-|^o[0-9]|codex"))          then "openai"
  elif ($m | test("gemini"))                      then "google"
  elif $c == "claude" or $c == "litellm"          then "anthropic"
  elif $c == "codex"                              then "openai"
  elif $c == "agy"                                then "google"
  elif $c == "copilot"                            then "github"
  elif $c == "bob"                                then "ibm"
  elif $c == "pi" or $c == "goose"                then "deepseek"
  else "unknown" end;'

# Providers this window applies to. Override to retune without editing code.
PEAK_PROVIDERS="${HIVE_PEAK_PROVIDERS:-deepseek}"

if [ "$ACTION" = status ]; then
  printf '%s' "$STATUS_JSON" | jq -r "$PROVIDER_JQ"'
    ["agent","provider","model","paused","trigger","reason"],
    (.agents[] | [.name, provider, (.govModel//"-"), (.paused|tostring),
                  (.pausedTrigger//"-"), (.pausedReason//"-")])
    | @tsv' | column -t -s $'\t'
  echo
  echo "peak applies to provider(s): $PEAK_PROVIDERS"
  [ -s "$STATE" ] && echo "peak-paused set: $(tr '\n' ' ' < "$STATE")"
  exit 0
fi

if [ "$ACTION" = pause ]; then
  # Two filters, both necessary:
  #  - .paused != true  — anything already paused was paused by something else
  #    (e.g. the login-detector) and must be left alone, so resume never adopts it.
  #  - provider in PEAK_PROVIDERS — an agent rotated onto another provider is
  #    not affected by this window and must keep working through it.
  TARGETS=$(printf '%s' "$STATUS_JSON" \
    | jq -r --arg peak "$PEAK_PROVIDERS" "$PROVIDER_JQ"'
        ($peak | split(" ")) as $want
        | .agents[]
        | select(.paused != true)
        | select([provider] | inside($want))
        | .name')
  SKIPPED=$(printf '%s' "$STATUS_JSON" \
    | jq -r --arg peak "$PEAK_PROVIDERS" "$PROVIDER_JQ"'
        ($peak | split(" ")) as $want
        | .agents[]
        | select(.paused != true)
        | select([provider] | inside($want) | not)
        | "\(.name)(\(provider))"' | tr '\n' ' ')
  [ -n "$SKIPPED" ] && echo "not on a peak provider, left running: $SKIPPED"
else
  # Restore exactly the set this script paused. No state file means we never
  # paused anything — resuming everything here is what would clobber the
  # login-detector's pauses, so do nothing instead.
  if [ ! -s "$STATE" ]; then
    echo "nothing to resume: no recorded peak-pause set at $STATE"
    exit 0
  fi
  TARGETS=$(cat "$STATE")
fi

if [ -z "$TARGETS" ]; then
  echo "nothing to $ACTION"
  exit 0
fi

mkdir -p "$(dirname "$STATE")"
rc=0
done_agents=()
for a in $TARGETS; do
  out=$(hive_api POST "/api/$ACTION/$a")
  if [ "$(printf '%s' "$out" | jq -r '.ok // empty' 2>/dev/null)" = "true" ]; then
    echo "ok: $ACTION $a -> $(printf '%s' "$out" | jq -r '.status // "-"')"
    done_agents+=("$a")
  else
    echo "FAIL: $ACTION $a -> ${out:0:200}"
    rc=1
  fi
done

# Record only what actually succeeded, so a partial pause resumes exactly the
# agents it really paused.
if [ "$ACTION" = pause ]; then
  printf '%s\n' "${done_agents[@]+"${done_agents[@]}"}" > "$STATE"
else
  rm -f "$STATE"
fi

exit $rc
