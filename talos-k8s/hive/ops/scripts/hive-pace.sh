#!/usr/bin/env bash
# hive-pace.sh — burn-rate pacing for the tuna-os Hive fleet.
#
# WHY THIS EXISTS
# ---------------
# hive-rotate.sh knows THRESHOLDS: a pool is fine at 84% and evacuated at 85%.
# That is the right model for "can this provider serve at all", and the wrong
# model for "should we be going this fast". A threshold cannot see either of
# the two ways a subscription cap is wasted:
#
#   OVERBURN  — 22 agents took Anthropic 64% -> 67% in ~25 minutes against a
#               weekly cap resetting six hours later. The threshold is silent
#               until 90%, at which point the fleet parks and sits idle for
#               hours with quota it could not spend because it spent it early.
#   UNDERBURN — a cap that resets UNUSED is quota destroyed. The threshold has
#               nothing to say about this at all; it is only ever a brake.
#
# Pacing is the missing half: spend the pool so it lands near-empty exactly at
# its reset, and no earlier.
#
# HEADROOM IS NOT A SCALAR
# ------------------------
# The single most important thing this script gets right, and the thing the
# collapsed `probe` number hides. Anthropic returns SEVERAL concurrent limits
# on INDEPENDENT clocks. Measured 2026-09-02T16:55Z:
#
#     percent  37   resets 19:30   (5h session window)
#     percent  67   resets 23:00   (weekly)
#     percent 100   resets 23:00   scope.model="Fable"   (model-class cap)
#
# `probe` reports "67% resets=23:00" — the largest unscoped limit. For an
# availability question that is correct. For a RATE question it is wrong:
#
#     session: 63 points over 2.6h -> 24.2 %/hr allowed
#     weekly:  33 points over 6.1h ->  5.4 %/hr allowed
#
# The binding constraint is whichever limit is closest to violating its own
# deadline, and that is not knowable from the maximum percent. Worse, the two
# percentages are on DIFFERENT SCALES — 1% of the session pool is not 1% of the
# weekly pool — so the rates cannot be compared directly either.
#
# The scale-free formulation is a RATIO, which is what this script computes:
#
#     pressure = max over limits of ( observed_rate_i / allowed_rate_i )
#
# pressure > 1 means at least one limit will hit 100% before it resets.
# pressure < 1 means every limit will reset with quota unspent.
# Both are failures. 1.0 is the target, and the deadband makes it a band.
#
# Model-SCOPED limits are excluded, exactly as in probe_anthropic: a
# weekly_scoped{model:"Fable"} at 100% caps one model class, not the account,
# and treating it as provider exhaustion parked an 11-agent fleet while Sonnet
# answered normally throughout.
#
# WHAT IT ACTUATES
# ----------------
# Placement (move an agent to another provider) is hive-rotate.sh's job and is
# only a pacing lever when another pool has room — with DeepSeek dry, OpenAI
# unseated and Google in its own cooldown there are periods with exactly one
# usable pool and placement has ZERO degrees of freedom. So the actuator here
# is the one that works even then: MODEL RUNG. Moving an agent from a
# provider's expensive rung to its cheap rung (opus->sonnet) is a large change
# in burn rate against the same cap, and needs no second provider.
#
# It only ever moves agents it can name a reason for, and only ever restores
# agents IT ITSELF demoted (tracked in pace-demoted). An agent the operator or
# the rotator deliberately placed on the cheap rung is never promoted by the
# pacer — that would silently overrule a decision made elsewhere.
#
# CONTROL AUTHORITY IS PARTIAL, AND SAID SO OUT LOUD
# --------------------------------------------------
# The Anthropic pool is drained by school's 11 agents, reef's 11, AND the
# contributor CLIs, which take work from hubs this script does not manage. A
# pacer that actuates 22 of ~23 consumers, observes no rate change because the
# unmanaged one absorbed the slack, and sheds again, is a runaway. So the
# verdict always reports how many consumers it actually controls, and the
# actuator moves ONE NOTCH PER TICK with a deadband — never a proportional
# correction computed from an error it may not fully own.
#
# USAGE
#   hive-pace.sh record     # take a reading, append to history, no decisions
#   hive-pace.sh status     # rate, pressure and verdict per provider
#   hive-pace.sh apply      # record + status + actuate one notch
#
# Env:
#   HIVE_PACE_STATE        state dir (default shares hive-rotate's)
#   HIVE_PACE_NAMESPACES   hives to actuate (default "hive hive-reef")
#   HIVE_PACE_DEADBAND     fraction either side of 1.0 that counts as on-pace
#                          (default 0.25 -> hot above 1.25, cold below 0.75)
#   HIVE_PACE_MIN_SAMPLES  samples needed before any verdict (default 3)
#   HIVE_PACE_MIN_SPAN_S   seconds the samples must span (default 3600)
#   HIVE_PACE_DRYRUN=1     compute and publish, actuate nothing

set -u

# Shared plumbing (hive-lib.sh): kubeconfig, API over the hive Service, slim
# /api/status, cached owner session, curl-based ConfigMap reads/writes, and
# rung_down (shared with hive-rotate so the two agree on what a demoted rung is).
# shellcheck source=hive-lib.sh
. "${HIVE_LIB:-$(dirname "$0")/hive-lib.sh}"
hive_kube_env

STATE_DIR="${HIVE_PACE_STATE:-${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}}"
NAMESPACES="${HIVE_PACE_NAMESPACES:-hive hive-reef}"
DEADBAND="${HIVE_PACE_DEADBAND:-0.25}"
MIN_SAMPLES="${HIVE_PACE_MIN_SAMPLES:-3}"
MIN_SPAN_S="${HIVE_PACE_MIN_SPAN_S:-3600}"

HISTORY="$STATE_DIR/pace-history.jsonl"
DEMOTED="$STATE_DIR/pace-demoted"
mkdir -p "$STATE_DIR"
# touch, NOT truncate. This file is the pacer's only memory of which agents it
# demoted; emptying it each run would make every demotion permanent, since the
# cold branch restores only what it can find here.
touch "$DEMOTED" 2>/dev/null || true
# Compact to the latest row per agent (re-demotions used to append; 68 rows
# for one agent accumulated while rotate and pace fought).
if [ -s "$DEMOTED" ]; then
  tac "$DEMOTED" | awk -F'|' '!seen[$1]++' | tac > "$DEMOTED.tmp" 2>/dev/null && mv "$DEMOTED.tmp" "$DEMOTED"
fi

ACTION="${1:-status}"
case "$ACTION" in record|status|apply) ;; *) echo "usage: $0 record|status|apply" >&2; exit 2 ;; esac
[ "${HIVE_PACE_DRYRUN:-0}" = 1 ] && [ "$ACTION" = apply ] && ACTION=status

NOW=$(date -u +%s)

# ── Model rungs ─────────────────────────────────────────────────────────
# expensive rung -> cheap rung, per provider. Deliberately NOT read from
# hive-rotate.sh's TIERS table: this script decides by looking at what an agent
# is ACTUALLY running, so it cannot drift out of sync with a table it does not
# consult. deepseek has no pair — v4-flash is already both its T1 and T2 rung
# (it outscores Sonnet on TB2.1 while costing a fraction), so there is nothing
# below it to demote to.
# rung_down <model> lives in hive-lib.sh. Added 2026-09-24: claude-fable-5-1
# (the live T1 rung from the tier cache) had no cheaper pair, so anthropic ran
# `hot` with "SATURATED ... 0 demotable" while two agents sat on it.

# The ACCOUNT an agent burns, from backend + model (hive_provider_of in
# hive-lib.sh, shared with hive-rotate). Model-name-only classification
# counted a copilot agent running claude-fable-5 as Anthropic and "demoted"
# it (2026-09-24) — copilot bills GitHub, so that changed nothing about the
# Anthropic burn. Only the four paced pools are returned; anything else
# (github, meta, unknown) is outside the pacer's control.
provider_of_agent() {
  local p; p=$(hive_provider_of "$1" "$2")
  case "$p" in anthropic|google|openai|deepseek) echo "$p" ;; *) echo "" ;; esac
}

# ── Reading: per-limit, not collapsed ───────────────────────────────────
# EVERYTHING is read from the ConfigMap hive-rotate publishes. The pacer makes
# no provider calls of its own, deliberately:
#
#   api.anthropic.com/api/oauth/usage RATE LIMITS. Adding a second poller
#   beside hive-rotate's existing 20-minute probe produced
#   `{"error":{"type":"rate_limit_error"}}` immediately, and it degrades BOTH
#   readings — the pacer's and the rotator's — so the fleet loses its
#   availability signal to feed its pacing signal. Measuring a provider harder
#   is not the same as measuring it better.
#
#   google/openai headroom is readable ONLY by typing a slash command into a
#   live CLI pane; duplicating that would double the load on the panes too.
#
# So hive-rotate probes once and publishes; every consumer reads the
# publication. hive-rotate's probe_anthropic writes the FULL unscoped limit
# array to the `anthropic_limits` key precisely for this.
#
# Slots are pre-sorted by reset ascending on the publishing side, so the slot
# index is STABLE across ticks. Keying history on the reset timestamp itself
# looks more natural and breaks on a rolling window, where the stamp moves
# every tick and no history ever accumulates. Rollover is detected from the
# percent dropping instead (see the fit), which works for both.
#
# Emits TSV: slot <TAB> percent <TAB> reset_epoch
USAGE_DATA=""
usage_data() {  # the published hive-provider-usage .data, fetched once per run
  [ -n "$USAGE_DATA" ] || USAGE_DATA=$(k8s_get /api/v1/namespaces/hive/configmaps/hive-provider-usage | jq -c '.data // {}' 2>/dev/null)
  printf '%s' "${USAGE_DATA:-{\}}"
}

read_limits_anthropic() {
  local raw
  raw=$(usage_data | jq -r '.anthropic_limits // empty')
  # Fall back to the collapsed single-limit view if the rotator has not yet
  # published the detailed key (first run after this change, or an old script).
  # Coarser, but it keeps the pacer working instead of silently blind.
  [ -z "$raw" ] && { read_limits_from_configmap anthropic; return; }
  printf '%s' "$raw" | jq -r 'try (.[] | "\(.slot)\t\(.percent)\t\(.resets_at)") // empty' 2>/dev/null \
  | while IFS=$'\t' read -r slot pct rst; do
      ep=$(python3 -c "
import datetime,sys
try: print(int(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))
except Exception: print('')" "$rst" 2>/dev/null)
      [ -n "$ep" ] && printf '%s\t%s\t%s\n' "$slot" "$pct" "$ep"
    done
}

read_limits_from_configmap() {
  local p="$1" raw pct rst ep
  raw=$(usage_data | jq -r --arg p "$p" '.[$p] // empty')
  [ -z "$raw" ] && return 1
  pct=$(printf '%s' "$raw" | grep -oE '^[0-9]+' | head -1)
  [ -z "$pct" ] && return 1            # "unknown ..." — not a measurement
  rst=$(printf '%s' "$raw" | grep -oE 'resets=[^ ]+' | sed 's/^resets=//')
  ep=""
  [ -n "$rst" ] && ep=$(python3 -c "
import datetime,sys
try: print(int(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))
except Exception: print('')" "$rst" 2>/dev/null)
  # No parseable reset means no deadline, and without a deadline there is no
  # such thing as an allowed rate. Emit the sample anyway so history is
  # continuous, with an empty reset the fit will skip.
  printf 'slot0\t%s\t%s\n' "$pct" "${ep:-}"
}

record() {
  local p slot pct ep
  for p in anthropic google openai deepseek; do
    if [ "$p" = anthropic ]; then
      read_limits_anthropic
    else
      read_limits_from_configmap "$p"
    fi | while IFS=$'\t' read -r slot pct ep; do
        [ -z "${pct:-}" ] && continue
        printf '{"ts":%s,"provider":"%s","slot":"%s","pct":%s,"reset":%s}\n' \
          "$NOW" "$p" "$slot" "$pct" "${ep:-null}" >> "$HISTORY"
      done
  done
  # Bound the file. 24h at a 20-minute tick is ~72 ticks x ~5 rows; 2000 lines
  # is generous headroom and keeps the fit's input small enough to stay cheap.
  if [ "$(wc -l < "$HISTORY" 2>/dev/null || echo 0)" -gt 2000 ]; then
    tail -1200 "$HISTORY" > "$HISTORY.tmp" && mv "$HISTORY.tmp" "$HISTORY"
  fi
}

# ── The fit ─────────────────────────────────────────────────────────────
# Least squares over (hours, percent) per (provider, slot), which is the whole
# reason history exists: a two-point delta on an INTEGER percent is dominated
# by quantization. The 64->66 over ten minutes that prompted this script is
# "12 %/hr" only if both endpoints are exact; the true rate is somewhere in
# 6-18 %/hr and no controller should be built on it.
#
# Refuses to answer without MIN_SAMPLES points spanning MIN_SPAN_S. An
# unanswerable question returns verdict "learning", never a guess — the first
# runs after a deploy must fall through to hive-rotate's existing threshold
# behaviour, not to an invented rate.
compute() {
  python3 - "$HISTORY" "$NOW" "$MIN_SAMPLES" "$MIN_SPAN_S" "$DEADBAND" <<'PY'
import json, sys, collections

path, now, min_n, min_span, deadband = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])

rows = []
try:
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception: pass
except FileNotFoundError:
    pass

series = collections.defaultdict(list)
for r in rows:
    series[(r["provider"], r["slot"])].append(r)

out = {}
for (prov, slot), pts in series.items():
    pts.sort(key=lambda r: r["ts"])

    # Window rollover. A cap that resets goes 67 -> 3, and averaging across
    # that boundary yields a large NEGATIVE burn rate, which reads as "wildly
    # underburning" and would floor the accelerator at the exact moment a
    # fresh window starts. Any drop of more than 5 points starts a new window;
    # so does the reset timestamp moving forward, which is the same event seen
    # from the other side.
    cut = 0
    for i in range(1, len(pts)):
        if pts[i]["pct"] < pts[i-1]["pct"] - 5:
            cut = i
        elif pts[i].get("reset") and pts[i-1].get("reset") and pts[i]["reset"] > pts[i-1]["reset"] + 60:
            cut = i
    pts = pts[cut:]

    latest = pts[-1]
    span = pts[-1]["ts"] - pts[0]["ts"] if len(pts) > 1 else 0
    entry = {
        "pct": latest["pct"],
        "reset": latest.get("reset"),
        "samples": len(pts),
        "span_s": span,
    }

    if latest.get("reset"):
        hrs = (latest["reset"] - now) / 3600.0
        entry["hours_left"] = round(hrs, 2)
        # Allowed rate: spend what is left, evenly, over what time is left.
        entry["allowed_rate"] = round((100.0 - latest["pct"]) / hrs, 2) if hrs > 0.05 else None
    else:
        entry["hours_left"] = None
        entry["allowed_rate"] = None

    if len(pts) >= min_n and span >= min_span:
        # slope of pct vs hours, least squares
        xs = [(p["ts"] - pts[0]["ts"]) / 3600.0 for p in pts]
        ys = [float(p["pct"]) for p in pts]
        n = len(xs)
        mx, my = sum(xs)/n, sum(ys)/n
        den = sum((x-mx)**2 for x in xs)
        slope = (sum((x-mx)*(y-my) for x, y in zip(xs, ys)) / den) if den > 1e-9 else 0.0
        entry["observed_rate"] = round(slope, 2)
        if entry["allowed_rate"] and entry["allowed_rate"] > 0:
            entry["ratio"] = round(slope / entry["allowed_rate"], 2)
        # When will this limit hit 100% at the current rate?
        if slope > 0.01:
            entry["exhausts_in_h"] = round((100.0 - latest["pct"]) / slope, 2)
    out.setdefault(prov, {})[slot] = entry

verdicts = {}
for prov, slots in out.items():
    ratios = [s["ratio"] for s in slots.values() if s.get("ratio") is not None]
    if not ratios:
        verdicts[prov] = {"verdict": "learning", "pressure": None, "slots": slots}
        continue
    # The BINDING limit is the worst ratio, not the largest percent. This is
    # the whole point: 37%-with-2.6h-left and 67%-with-6.1h-left are different
    # allowances on different scales, and only the ratio compares them.
    pressure = max(ratios)
    binding = max(slots.items(), key=lambda kv: kv[1].get("ratio") or -1)[0]
    if pressure > 1 + deadband:   v = "hot"
    elif pressure < 1 - deadband: v = "cold"
    else:                          v = "on-pace"
    verdicts[prov] = {"verdict": v, "pressure": round(pressure, 2),
                      "binding_slot": binding, "slots": slots}

print(json.dumps(verdicts, indent=None, sort_keys=True))
PY
}

# ── Fleet view ──────────────────────────────────────────────────────────
# Every agent across every managed hive, with its CONFIGURED backend and model.
#
# The fields are `cli` and `govModel`, matching hive-rotate.sh. There is no
# `.backend` on an agent — reading one yields null for every agent, and this
# script's first version did exactly that and would have PUT an empty backend
# on the first actuation. `.model` exists but reports what the PANE currently
# shows; `govModel` is what the governor will launch next, which is the value
# the models endpoint writes. Read the field you write.
fleet() {
  local ns
  for ns in $NAMESPACES; do
    # hive_open: slim status via the Service (the old per-namespace 3 MB exec
    # read silently dropped two of three hives — "controls 12 agents").
    hive_open "$ns" 2>/dev/null || { echo "WARN: $ns unreadable — not paced this tick" >&2; continue; }
    printf '%s' "$STATUS_JSON" | jq -r --arg ns "$ns" '.agents[]?
        | "\($ns)\t\(.name)\t\(.cli // "")\t\(.govModel // .model // "")\t\(.paused // false)"' 2>/dev/null
  done
}

# Owner session cookie for a namespace. X-Hive-Internal authenticates reads and
# is READ-ONLY for mutations, so every model change needs a real session from
# the dashboard's own store. Read live so a fresh browser login is picked up
# with no edit here.
session_for() {
  local pod
  pod=$(hive_pod "$1"); [ -n "$pod" ] || return 1
  hive_session "$1" "$pod"
}

# Uses POST /api/model/{agent}/{model} — NOT PUT /api/config/agent/{a}/models.
#
# The config route returns {"ok":true,"status":"updated"} and does not change
# what the agent runs. Verified 2026-09-02 on the `hive` spoke: PUT ...
# /models with claude-opus-5 answered ok, cleared `model_override` in
# hive-state.json back to null, and left govModel on claude-sonnet-5 — the pack
# default reasserted. The same call DOES work on `hive-reef`, so this is
# ACMM-level-dependent (L6 vs L5) and cannot be trusted fleet-wide. An actuator
# that logs "demote" while changing nothing is worse than no actuator: the
# pacer would report itself in control while the burn ran on unchecked.
#
# hive-rotate has always used /api/model + /api/switch, which is why ITS
# placements stick. The pacer only ever moves along a rung WITHIN one provider
# (rung_down maps opus->sonnet, never across backends), so the model call alone
# is sufficient and there is no switch/model two-call transaction to get wrong.
#
# NOTE: /api/status lags a mutation by >10s, so a read-back immediately after
# this call still shows the OLD model. Do not treat that as failure.
set_model() {
  local ns="$1" agent="$2" backend="$3" model="$4" pod sid
  # Never write a blank. A missing field here does not fail loudly — it PUTs
  # an empty backend or model and unseats a working agent, which then looks
  # like a hive fault rather than a pacer fault.
  if [ -z "$backend" ] || [ -z "$model" ]; then
    echo "WARN: refusing to set $ns/$agent with empty backend/model" >&2
    return 1
  fi
  pod=$(hive_pod "$ns")
  sid=$(session_for "$ns")
  if [ -z "$pod" ] || [ -z "$sid" ]; then
    echo "WARN: $ns has no pod or no unexpired owner session — cannot actuate" >&2
    return 1
  fi
  local out
  # 150 s: v5 restarts the agent inside the request.
  out=$(hive_call "$ns" "$pod" "$sid" POST "/api/model/$agent/$model")
  # Judge by the response, not by exit status: a 200 carrying an error body is
  # a documented failure shape on this API.
  case "$out" in
    *'"status":"model_set"'*|*'"ok":true'*)
      # agy suffixes must match --effort or agy silently runs 3.6 Flash Low
      # (see hive-lib.sh agy_effort_of). The recorded effort lives with
      # hive-rotate's per-hive state so both scripts agree.
      local want edir
      edir="$(dirname "$STATE_DIR")/$( [ "$ns" = hive ] && echo hive-rotate || echo "hive-rotate-${ns#hive-}")/effort"
      want=$(effort_change "$backend" "$model" "$(cat "$edir/$agent" 2>/dev/null)")
      if [ -n "$want" ] && hive_call "$ns" "$pod" "$sid" POST "/api/effort/$agent/$want" | grep -q effort_set; then
        mkdir -p "$edir" && echo "$want" > "$edir/$agent"
      fi
      printf '%s' "$out"; return 0 ;;
    *) echo "WARN: model set for $ns/$agent -> $model did not confirm: ${out:0:160}" >&2
       return 1 ;;
  esac
}

publish() {
  local json="$1"
  k8s_put_cm hive hive-pace "$(jq -cn --arg j "$json" --arg u "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --arg c "$(printf '%s' "$FLEET" | grep -c . || echo 0) agents in: $NAMESPACES" \
      '{"pace.json":$j, updated_at:$u, controls:$c}')" \
    || echo "WARN: could not publish hive-pace ConfigMap" >&2
}

# ── Run ─────────────────────────────────────────────────────────────────
[ "$ACTION" = record ] && { record; echo "recorded $(date -u +%H:%M:%SZ)"; exit 0; }

record
VERDICTS=$(compute)
FLEET=$(fleet)

printf '%-11s %-9s %-9s %-11s %-11s %s\n' PROVIDER VERDICT PRESSURE OBSERVED ALLOWED DETAIL
for p in anthropic google openai deepseek; do
  row=$(printf '%s' "$VERDICTS" | jq -r --arg p "$p" '
    if .[$p] then
      .[$p] as $v
      | ($v.slots | to_entries | map(select(.key == ($v.binding_slot // "slot0"))) | .[0].value // {}) as $b
      | "\($v.verdict)\t\($v.pressure // "-")\t\($b.observed_rate // "-")\t\($b.allowed_rate // "-")\t\($b.pct)% used, \($b.hours_left // "?")h left, \($v.slots|length) limit(s), \($b.samples) sample(s)"
    else "no-data\t-\t-\t-\tnot measured" end' 2>/dev/null)
  IFS=$'\t' read -r v pr ob al det <<< "$row"
  # jq emits "-" for an absent number, so append the unit only to real values.
  [ "$ob" != "-" ] && ob="$ob %/hr"
  [ "$al" != "-" ] && al="$al %/hr"
  printf '%-11s %-9s %-9s %-11s %-11s %s\n' "$p" "$v" "$pr" "$ob" "$al" "$det"
done

echo
echo "controls $(printf '%s' "$FLEET" | grep -c . || echo 0) agents across: $NAMESPACES"
echo "NOTE: contributor CLIs draw on the same pools and are NOT actuated here."

publish "$VERDICTS"

[ "$ACTION" != apply ] && exit 0

# ── Actuate: one notch, deadbanded ──────────────────────────────────────
# One notch per tick on purpose. A proportional correction computed from an
# error this script only partly owns (the contributors are outside its control)
# is how a pacer turns into an oscillator.
moved=0
declare -A MOVED_ON    # provider -> already actuated this tick
declare -A SEATED      # provider -> agents currently running on it
declare -A DEMOTABLE   # provider -> agents that still have a cheaper rung
declare -A RESTORABLE  # provider -> agents this pacer demoted and could restore

while IFS=$'\t' read -r ns agent backend model paused; do
  [ -z "${agent:-}" ] && continue
  [ "$paused" = "true" ] && continue
  prov=$(provider_of_agent "$backend" "$model")
  [ -z "$prov" ] && continue
  SEATED[$prov]=$(( ${SEATED[$prov]:-0} + 1 ))

  cheap=$(rung_down "$model")
  [ -n "$cheap" ] && DEMOTABLE[$prov]=$(( ${DEMOTABLE[$prov]:-0} + 1 ))
  # Only a row whose demotion is still IN EFFECT (the agent sits on exactly
  # rung_down(original)) counts — the same rule hive-rotate uses. A stale row
  # must never "restore" an agent onto a rung the pacer did not take it from.
  demoted_from=$(pace_demoted_from "$DEMOTED" "$ns" "$agent" "$model")
  [ -n "$demoted_from" ] && RESTORABLE[$prov]=$(( ${RESTORABLE[$prov]:-0} + 1 ))

  verdict=$(printf '%s' "$VERDICTS" | jq -r --arg p "$prov" '.[$p].verdict // "no-data"')
  # One notch per tick PER PROVIDER. Keep scanning the rest of the fleet so the
  # counts above stay complete and so a second hot provider still gets its own
  # notch — an earlier version `break`ed out of the whole loop on the first
  # change, which silently meant reef was never actuated while school still had
  # a demotable agent.
  [ -n "${MOVED_ON[$prov]:-}" ] && continue

  case "$verdict" in
    hot)
      [ -z "$cheap" ] && continue            # already on the cheap rung
      if set_model "$ns" "$agent" "$backend" "$cheap" >/dev/null; then
        # One line per agent: re-demotions used to append duplicates (~25 for
        # reef/sec-check while rotate and pace fought over it).
        grep -vF "$ns/$agent|" "$DEMOTED" > "$DEMOTED.tmp" 2>/dev/null; mv "$DEMOTED.tmp" "$DEMOTED"
        echo "$ns/$agent|$backend|$model" >> "$DEMOTED"
        echo "  demote  $ns/$agent  $model -> $cheap  (${prov} hot)"
        MOVED_ON[$prov]=1; moved=$((moved+1))
      fi
      ;;
    cold)
      # Restore ONLY what this script demoted. An agent the operator or the
      # rotator placed on the cheap rung was placed there for a reason the
      # pacer cannot see, and promoting it would silently overrule that.
      [ -z "$demoted_from" ] && continue
      orig_backend=${demoted_from%%|*}
      orig_model=${demoted_from#*|}
      if set_model "$ns" "$agent" "$orig_backend" "$orig_model" >/dev/null; then
        grep -vF "$ns/$agent|" "$DEMOTED" > "$DEMOTED.tmp" 2>/dev/null && mv "$DEMOTED.tmp" "$DEMOTED"
        echo "  restore $ns/$agent  $model -> $orig_model  (${prov} cold)"
        MOVED_ON[$prov]=1; moved=$((moved+1))
      fi
      ;;
  esac
done <<< "$FLEET"

# ── Saturation ──────────────────────────────────────────────────────────
# The control range is FINITE and small: only agents on a provider's expensive
# rung can be demoted, and there are ~3 per hive. At one notch per tick a
# sustained overburn exhausts every notch in about two hours, after which the
# pacer reports `hot` forever while changing nothing — and "hot, 0 changes" is
# indistinguishable from "hot, nothing needed" unless it is said out loud.
#
# This is the line that means INTERVENE: the loop is no longer able to correct,
# and the remaining levers (cadence, pausing agents, accepting the burn) are
# outside this script.
for p in anthropic google openai deepseek; do
  v=$(printf '%s' "$VERDICTS" | jq -r --arg p "$p" '.[$p].verdict // "no-data"')
  [ "$v" = hot ] || continue
  [ -n "${MOVED_ON[$p]:-}" ] && continue
  # Nothing running on it means nothing to correct: a `hot` verdict with zero
  # seated agents is a stale rate from before the fleet moved off, not a
  # saturated actuator. Saying SATURATED there sends the operator after a
  # problem that no longer exists.
  [ "${SEATED[$p]:-0}" -gt 0 ] || continue
  echo "  SATURATED: $p is hot but no notch was available" \
       "(${DEMOTABLE[$p]:-0} of ${SEATED[$p]:-0} seated agents demotable)" \
       "— model-rung pacing is exhausted; needs cadence or capacity"
done

echo
echo "pace: $moved change(s)"
