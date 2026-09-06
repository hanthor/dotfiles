#!/usr/bin/env bash
# hive-nudge.sh — kick agents the governor has stopped scheduling.
#
# WHY
# ---
# The governor decides which agents are "due" and kicks them. On 2026-09-06 it
# stopped: school sat on 837 open issues in SURGE mode — where supervisor is on a
# 1-minute cadence and scanner on 5 — and returned `agents_due: null` on every
# eval for 7.9 hours. hanthor showed the same skew more mildly, kicking only
# supervisor while `guide` went 14 hours untouched. Nothing shipped for 7.7
# hours and no alarm fired anywhere, because every other layer was healthy:
# pods Running, panes `liveness ok`, providers with headroom, credentials fine.
#
# Kicking those agents by hand immediately produced work (quality: "Worked for
# 2m 29s"), which proves the kick path, the panes, the models and the
# credentials are all fine. The gap is scheduling alone.
#
# This does NOT fix the governor — that logic is in the Go binary. It is a
# backstop that converts "the fleet silently stops until a human notices" into a
# self-correcting condition.
#
# NOT FIGHTING THE GOVERNOR
# -------------------------
# The threshold is each agent's LONGEST cadence across every governor mode,
# times a grace factor. If an agent has not been kicked in longer than its own
# slowest schedule allows, no mode can explain it and something is wrong. Using
# the longest (not the current mode's) means this can never pre-empt a governor
# that is merely running in a slow mode — it only fires when the governor has
# genuinely stopped.
#
# Agents paused in EVERY mode (operations/telemetry are `paused` in this fleet)
# are never nudged: that is a deliberate config, not a stall.
#
# USAGE
#   hive-nudge.sh check    # report who is overdue, kick nothing
#   hive-nudge.sh nudge    # kick them

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

set -u

LABEL=app.kubernetes.io/name=hive
API=http://127.0.0.1:3002
NAMESPACES="${HIVE_NUDGE_NAMESPACES:-hive hive-reef hive-hanthor}"
GRACE="${HIVE_NUDGE_GRACE:-2}"          # multiples of the longest cadence; 2x its own slowest schedule is already anomalous
FLOOR_S="${HIVE_NUDGE_FLOOR_S:-1800}"   # never nudge anything idle < 30m
MAX_PER_NS="${HIVE_NUDGE_MAX_PER_NS:-4}"
ACTION="${1:-check}"
case "$ACTION" in check|nudge) ;; *) echo "usage: $0 check|nudge" >&2; exit 2;; esac

total=0

for ns in $NAMESPACES; do
  pod=$(kubectl get pods -n "$ns" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
  [ -n "$pod" ] || { printf '%-14s no hive pod — skipped\n' "$ns"; continue; }

  # Longest cadence per agent across ALL modes, in seconds. `paused` contributes
  # nothing, so an agent paused in every mode ends with no entry and is skipped.
  # Pull the raw governor block out with NO nested quoting (a `sh -c` wrapper
  # here silently mangles the awk and yields nothing), then parse locally.
  # Indentation in this file is 4 spaces for `modes:`, 8 for each mode name and
  # 12 for each agent cadence.
  raw=$(kubectl exec -n "$ns" "$pod" -- \
        sed -n '/^governor:/,/^[a-z_]*:/p' /data/hive.yaml.runtime 2>/dev/null)
  cad=$(printf '%s\n' "$raw" | awk '
      /^    modes:/            { inm=1; next }
      inm && /^    [a-z_]+:/   { inm=0 }
      inm && /^            [a-zA-Z_-]+: / {
        name=$1; sub(/:$/,"",name)
        if (name == "threshold") next
        d=$2; s=0
        if      (d ~ /^[0-9]+m$/) { sub(/m/,"",d); s=d*60 }
        else if (d ~ /^[0-9]+h$/) { sub(/h/,"",d); s=d*3600 }
        else if (d ~ /^[0-9]+s$/) { sub(/s/,"",d); s=d+0 }
        else next                      # "paused" and anything unparseable
        if (s > max[name]) max[name]=s
      }
      END { for (a in max) print a, max[a] }')
  [ -n "$cad" ] || { printf '%-14s could not read cadences — skipped\n' "$ns"; continue; }

  # Compute idle AGE inside the hive pod, not here. last_kick is ISO-8601 with
  # fractional seconds and a numeric offset; the ops image is Alpine and busybox
  # `date -d` rejects that format outright, so the first version of this script
  # silently `continue`d on every agent and reported "nothing overdue" on a fleet
  # that had been idle for hours. The hive pod has GNU date, so ask it.
  kicks=$(kubectl exec -n "$ns" "$pod" -- sh -c '
    now=$(date -u +%s)
    jq -r ".agents | to_entries[] | \"\(.key) \(.value.last_kick // \"never\")\"" \
      /data/hive-state.json 2>/dev/null |
    while read -r a t; do
      if [ "$t" = "never" ]; then echo "$a 999999"
      else e=$(date -u -d "$t" +%s 2>/dev/null) && echo "$a $(( now - e ))" || echo "$a 999999"
      fi
    done' 2>/dev/null)

  tok=$(kubectl get secret -n "$ns" hive-secrets -o jsonpath='{.data.HIVE_DASHBOARD_TOKEN}' 2>/dev/null | base64 -d)
  live=$(kubectl exec -n "$ns" "$pod" -- curl -sS -m 20 -H "X-Hive-Internal: $tok" "$API/api/status" 2>/dev/null)
  [ -n "$live" ] || { printf '%-14s /api/status unreadable — skipped\n' "$ns"; continue; }

  sid=""
  if [ "$ACTION" = nudge ]; then
    sid=$(kubectl exec -n "$ns" "$pod" -- cat /data/dashboard-sessions.json 2>/dev/null \
          | jq -r 'to_entries|map(select(.value.Role=="owner"))|sort_by(.value.ExpiresAt)|reverse|.[0].key // empty')
    [ -n "$sid" ] || { printf '%-14s no owner session — cannot kick; log in at this spoke\n' "$ns"; continue; }
  fi

  done_ns=0
  while read -r agent maxs; do
    [ -n "$agent" ] || continue
    [ "$done_ns" -ge "$MAX_PER_NS" ] && break

    eligible=$(printf '%s' "$live" | jq -r --arg a "$agent" \
      '.agents[]? | select(.name==$a) | select((.paused|not) and (.enabled != false) and (.onDemand != true)) | .name' 2>/dev/null)
    [ -n "$eligible" ] || continue

    idle=$(printf '%s\n' "$kicks" | awk -v a="$agent" '$1==a {print $2}')
    [ -n "$idle" ] || continue

    thr=$(( maxs * GRACE ))
    [ "$thr" -lt "$FLOOR_S" ] && thr=$FLOOR_S
    [ "$idle" -le "$thr" ] && continue

    printf '%-14s %-14s idle %sm > %sm (longest cadence %sm x%s)' \
      "$ns" "$agent" "$(( idle / 60 ))" "$(( thr / 60 ))" "$(( maxs / 60 ))" "$GRACE"
    if [ "$ACTION" = check ]; then printf ' — would nudge\n'; total=$((total+1)); continue; fi

    # Sequential, generous timeout, small cap: this API times out under
    # concurrent mutations (observed at 25s and even 60s during a manual sweep).
    resp=$(kubectl exec -n "$ns" "$pod" -- curl -sS -m 75 -X POST \
             -H "Cookie: hive_session=$sid" "$API/api/kick/$agent" 2>&1)
    if printf '%s' "$resp" | grep -q '"ok":true'; then
      printf ' — kicked\n'; total=$((total+1)); done_ns=$((done_ns+1))
    else
      printf ' — KICK FAILED: %s\n' "$(printf '%s' "$resp" | head -c 80)"
    fi
    sleep 5
  done <<EOF
$cad
EOF
done

if [ "$total" = 0 ]; then
  echo "nudge: nothing overdue"
else
  echo "nudge: $total agent(s) $([ "$ACTION" = check ] && echo 'would be nudged' || echo 'nudged')"
fi
