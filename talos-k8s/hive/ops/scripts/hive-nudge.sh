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

# shellcheck source=hive-lib.sh
. "${HIVE_LIB:-$(dirname "$0")/hive-lib.sh}"
hive_kube_env

set -u

NAMESPACES="${HIVE_NUDGE_NAMESPACES:-hive hive-reef hive-hanthor}"
GRACE="${HIVE_NUDGE_GRACE:-2}"          # multiples of the longest cadence; 2x its own slowest schedule is already anomalous
FLOOR_S="${HIVE_NUDGE_FLOOR_S:-1800}"   # never nudge anything idle < 30m
MAX_PER_NS="${HIVE_NUDGE_MAX_PER_NS:-4}"
ACTION="${1:-check}"
case "$ACTION" in check|nudge) ;; *) echo "usage: $0 check|nudge" >&2; exit 2;; esac

total=0
START=$(date +%s)
failed=0

for ns in $NAMESPACES; do
  pod=$(hive_pod "$ns")
  [ -n "$pod" ] || { printf '%-14s no hive pod — skipped\n' "$ns"; continue; }

  # ONE exec for both in-pod reads (it used to be two, plus a 3 MB /api/status
  # streamed through a third that --max-time 20 truncated on v5):
  #   - the governor block of the runtime config: longest cadence per agent
  #     across ALL modes. Indentation is 4 spaces for `modes:`, 8 per mode,
  #     12 per agent cadence. `paused` contributes nothing, so an agent paused
  #     in every mode gets no entry and is skipped.
  #   - idle AGE per agent from hive-state.json last_kick, computed with the
  #     hive pod's GNU date (the ops image is busybox, whose `date -d` rejects
  #     ISO-8601 with fractional seconds and an offset — the first version of
  #     this script silently skipped every agent that way).
  # shellcheck disable=SC2016
  both=$(timeout 60 kubectl exec -n "$ns" "$pod" -- sh -c '
    echo "=====CAD"
    sed -n "/^governor:/,/^[a-z_]*:/p" /data/hive.yaml.runtime 2>/dev/null
    echo "=====KICKS"
    now=$(date -u +%s)
    jq -r ".agents | to_entries[] | \"\(.key) \(.value.last_kick // \"never\")\"" \
      /data/hive-state.json 2>/dev/null |
    while read -r a t; do
      if [ "$t" = "never" ]; then echo "$a 999999"
      else e=$(date -u -d "$t" +%s 2>/dev/null) && echo "$a $(( now - e ))" || echo "$a 999999"
      fi
    done' 2>/dev/null)
  raw=$(printf '%s\n' "$both" | sed -n '/^=====CAD$/,/^=====KICKS$/p' | sed '1d;$d')
  kicks=$(printf '%s\n' "$both" | sed -n '/^=====KICKS$/,$p' | sed '1d')
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

  sid=$(hive_sid "$ns" "$pod")
  [ -n "$sid" ] || { printf '%-14s no owner session — log in at this spoke\n' "$ns"; continue; }
  live=$(hive_status "$ns" "$pod" "$sid") \
    || { printf '%-14s /api/status unreadable — skipped\n' "$ns"; continue; }

  # NEVER nudge a spoke whose token budget is exhausted. The governor suppresses
  # kicks on purpose when weekly spend passes the limit ("budget exhausted —
  # suppressing kicks"), and that is a cost control, not a stall. Nudging past it
  # spends money the operator explicitly capped.
  #
  # This is the whole reason this script nearly did harm: school looked like a
  # governor that had stopped scheduling — `agents_due: null` for 7.9 hours on
  # 837 open issues — and was in fact a governor correctly refusing to spend at
  # 190% of a 50M weekly budget. The distinguishing evidence is in /api/status,
  # not in the eval log line.
  if [ "$(printf '%s' "$live" | jq -r '.budget.BUDGET_EXHAUSTED // false' 2>/dev/null)" = "true" ]; then
    printf '%-14s budget exhausted (%s%% of %s) — NOT nudging; this is a cost control, not a stall\n' \
      "$ns" \
      "$(printf '%s' "$live" | jq -r '.budget.BUDGET_PCT_USED // 0 | floor' 2>/dev/null)" \
      "$(printf '%s' "$live" | jq -r '.budget.BUDGET_WEEKLY // 0' 2>/dev/null)"
    continue
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

    # Sequential and capped. v5's kick is ASYNC: 202 {"ok":true,"status":
    # "queued"|"in-flight"} means accepted; delivery is reported later by
    # GET /api/kick/{agent}/status. The POST should answer in seconds. It
    # hangs when that agent's PREVIOUS delivery is still waiting (up to 120 s)
    # for an input prompt the wedged CLI never shows — v5 holds the agent's
    # lock meanwhile (school 2026-09-24: six kicks x 75 s blew the 600 s
    # deadline). So: short timeout, skip that agent, keep going within the run
    # budget. A timed-out kick may still have been queued. Wedged agents are
    # the watchdog's job (stall detector -> restart), not nudge's.
    if [ $(( $(date +%s) - START )) -ge "${HIVE_NUDGE_BUDGET_S:-420}" ]; then
      printf ' — skipped (run budget spent)\n'; continue
    fi
    resp=$(hive_call "$ns" "$pod" "$sid" POST "/api/kick/$agent" "${HIVE_NUDGE_KICK_TIMEOUT:-30}")
    if printf '%s' "$resp" | grep -q '"ok":true'; then
      printf ' — kicked (%s)\n' "$(printf '%s' "$resp" | jq -r '.status // "ok"')"; total=$((total+1)); done_ns=$((done_ns+1))
    elif printf '%s' "$resp" | grep -q 'transport rc='; then
      printf ' — kick not answered in %ss (agent likely wedged mid-delivery); skipped\n' "${HIVE_NUDGE_KICK_TIMEOUT:-30}"
      failed=$((failed+1))
    else
      printf ' — KICK FAILED: %s\n' "$(printf '%s' "$resp" | jq -r '.error // .' 2>/dev/null | head -c 100)"
    fi
    sleep 5
  done <<EOF
$cad
EOF
done

if [ "$failed" -gt 0 ]; then
  echo "nudge: $total kicked, $failed not answered"
elif [ "$total" = 0 ]; then
  echo "nudge: nothing overdue"
else
  echo "nudge: $total agent(s) $([ "$ACTION" = check ] && echo 'would be nudged' || echo 'nudged')"
fi
