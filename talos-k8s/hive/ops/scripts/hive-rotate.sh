#!/usr/bin/env bash
# hive-rotate.sh — capability-preserving backend rotation for the tuna-os Hive.
#
# WHY THIS EXISTS
# ---------------
# Hive's `governor.budget` counts tokens against a number YOU configure. It has
# no idea about the Claude Max weekly limit, the ChatGPT Plus weekly limit, or
# the Kiro Power monthly credits — and those are what actually stop work. They
# are per-ACCOUNT, and only each client knows its own headroom.
#
# DEEPSEEK IS GONE (2026-09-24): the owner is not topping the balance up again.
# Its rungs, probe and peak-window avoidance were removed; KIRO (the owner's
# Kiro Power subscription, run through `pi` + the pi-kiro-api provider — see
# hive-pi-kiro.sh) took its place as the subscription pool with the most room.
#
# This script closes that gap:
#   1. probe    — ask each provider how much headroom is left
#   2. decide   — pick a target rung per agent from a capability-tier table
#   3. rotate   — move agents sideways along their tier to a provider with room
#
# Rotation moves SIDEWAYS along a capability tier (same competence, different
# provider) and only drops a tier when no provider has headroom at that level.
# Moving `architect` off an exhausted frontier model onto whatever happens to be
# free would silently downgrade the fleet's most leveraged work.
#
# PROVIDER, NOT BACKEND
# ---------------------
# Cooldown keys on PROVIDER. `pi`/`goose` are shells over a configured provider;
# `claude`/`litellm` can share one Anthropic pool. Two backends on one exhausted
# account must both be skipped, and rotating claude->litellm on an Anthropic
# outage just burns another task rediscovering the same dead pool.
#
# AUTH
# ----
# Mutations need an OWNER SESSION COOKIE (`hive_session`). On this direct-route
# spoke `Authorization: Bearer` is rejected, forged X-Hive-User/X-Hive-Role are
# rejected, and `X-Hive-Internal` authenticates but is READ-ONLY. See
# hive-peak.sh for the full ladder. Sessions are read live from the pod's own
# store so a fresh browser login is picked up with no edit here.
#
# USAGE
#   hive-rotate.sh probe                 # headroom for every provider
#   hive-rotate.sh plan                  # what it would do, no changes
#   hive-rotate.sh apply                 # do it
#   hive-rotate.sh restore               # return every agent to its home rung
#   hive-rotate.sh watchdog              # liveness heal pass (CronJob every 5 min)
#   hive-rotate.sh contributors          # contributor replica reconcile only
#
# Env:
#   HIVE_ROTATE_THRESHOLD  rotate off a provider at/above this % used (default 85)
#   HIVE_PEAK_PROVIDERS    providers treated as unavailable during peak windows
#   HIVE_PEAK_WINDOWS      UTC HH:MM-HH:MM,... when those providers are avoided
#                          (weekdays only since DeepSeek's 2026-08-23 policy
#                          change: weekends are all-day off-peak)
#   HIVE_ROTATE_METERED_FAILOVER=0  retain the old high-volume strand-on-exhaustion policy
#   HIVE_ROTATE_DRYRUN=1   force plan-only (apply -> plan; watchdog reports only)
#   HIVE_USAGE_MAX_AGE_S   reuse a published measurement younger than this
#                          (default: primary apply 0, spoke apply 1200,
#                          watchdog 1800; `probe` always measures)


# Shared plumbing (kubeconfig, API over the hive Service, slim /api/status,
# pure decision helpers). See hive-lib.sh for why each piece exists.
# shellcheck source=hive-lib.sh
. "${HIVE_LIB:-$(dirname "$0")/hive-lib.sh}"
hive_kube_env

set -u

# Which hive this run manages. Overridable because the fleet is no longer ONE
# spoke: reef ran for hours with 7 of 11 agents parked on the Claude Code
# login-method picker and nothing healed them, because the watchdog only ever
# looked at `hive`. An unwatched spoke fails silently and indefinitely — its
# agents still report state=running and busy=working while the pane shows a
# login prompt, so nothing short of a pane check notices.
#
# Contributor reconciliation is deliberately NOT per-hive (see CONTRIB_NS): the
# contributor deployments are a single fleet-wide pool, so only the run that
# manages the primary hive should touch them.
NS="${HIVE_NS:-hive}"
STATE_DIR="${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}"
# No provider is peak-priced any more (DeepSeek was the only one). The knob is
# kept so a future metered pool can opt back in.
PEAK_PROVIDERS="${HIVE_PEAK_PROVIDERS:-}"
PEAK_WINDOWS="${HIVE_PEAK_WINDOWS:-01:00-04:00,06:00-10:00}"

RUN_START=$(date +%s)
ACTION="${1:-plan}"
case "$ACTION" in probe|plan|apply|restore|watchdog|contributors) ;; *) echo "usage: $0 probe|plan|apply|restore|watchdog|contributors" >&2; exit 2;; esac
[ "${HIVE_ROTATE_DRYRUN:-0}" = 1 ] && [ "$ACTION" = apply ] && ACTION=plan

mkdir -p "$STATE_DIR"

# ── Capability tiers, sourced from third-party agentic rankings ─────────
# Terminal-Bench 2.1 (retrieved 2026-08-15). TB2.1 is the right benchmark: it
# measures agents doing real terminal/CLI work, which is what hive agents do.
#
#   GPT-5.6 Sol .............. 89.5   Claude Opus 5 ............ 89.1
#   DeepSeek V4 Pro 0813 ..... 87.9   Claude Code + Fable 5 .... 83.8
#   Codex + GPT-5.5 .......... 83.1   DeepSeek V4-Flash 0731 ... 82.7
#   Codex + GPT-5.6 Terra .... 78.4   Codex + GPT-5.6 Luna ..... 75.7
#   Claude Code + Sonnet 5 ... 74.6   Gemini 3 Pro (Gemini CLI). 65.8
#
# CAVEAT: tbench.ai scores AGENT+MODEL pairs; Artificial Analysis scores
# model+effort. They are not directly comparable. Gemini 3 Pro swings 73.9
# (Terminus 2) vs 65.8 (Gemini CLI) on harness alone — so harness-paired numbers
# are the ones that predict THIS fleet, since hive runs these CLIs specifically.
#
# History: deepseek-flash (82.7) used to be the DEFAULT rung at T1-T3 on cost
# and capability. It was removed 2026-09-24 when the owner stopped topping up
# the DeepSeek balance; the Kiro rungs (same frontier Claude/GPT models, on a
# subscription nobody else draws on) took over its role. See `git log` for the
# DeepSeek rung rationale (V4-Flash over V4-Pro) if it ever comes back.
#
# ANTHROPIC RUNG MODELS ARE OVERRIDABLE, and this is a pacing lever, not a
# convenience. The table's job is to name a CAPABILITY FLOOR per tier; picking
# Sonnet at T2 is a COST choice on top of that. When the subscription cap is
# going to reset with quota unspent, that cost choice is backwards — unspent
# quota is destroyed, so the cheaper model saves nothing and merely produces
# worse work. Raising T2 to Opus converts an expiring surplus into better
# output without a single extra GitHub API call, which matters because the
# shared App installation (7100/hr) is the resource that actually runs out
# first when you try to spend quota by kicking harder instead.
#
# Safe to leave raised: hive-pace.sh demotes opus->sonnet automatically if the
# burn goes hot, so the failure mode of forgetting to revert this is "the
# pacer pulls it back", not "the cap is blown".
T1_ANTHROPIC_MODEL="${HIVE_ROTATE_T1_ANTHROPIC_MODEL:-claude-opus-5}"
T2_ANTHROPIC_MODEL="${HIVE_ROTATE_T2_ANTHROPIC_MODEL:-claude-sonnet-5}"

# The one muse/Meta rung this fleet places. Named once so probe_meta and the
# TIERS table cannot drift apart — a probe that health-checks a different id
# than the one rotation places would report green for a rung that fails.
# (Assigned HERE, above TIERS, because the table expands it at assignment.)
#
# 1.3, not 1.2 (2026-09-23): the pod's own GET /v1/models catalog now offers
# muse-spark-1.3-contributor (plus bare 1.3/1.2/1.1, voice, sam-3.1) — the
# 2026-09-08 caller-dependent blockage is resolved with the rotated key, live-
# verified from inside the hive pod. T2 placement still holds a fortiori: the
# AA 44.2 floor was measured for 1.2-xhigh and every vendor number has 1.3
# ahead of it (TB2.1 88.8 vs 82.9, ~20% fewer tool calls), so 1.3 at the 1.2
# rung is the conservative direction. T1 stays unjustified: no AA-scale score
# exists for any 1.3 variant, and vendor-harness numbers are not fleet numbers.
META_MODEL="${HIVE_META_MODEL:-muse-spark-1.3-contributor}"

# MODEL ID HISTORY. muse's catalog is CALLER-DEPENDENT: measured 2026-09-08
# with one and the same API key, GET https://api.meta.ai/v1/models returned
# SEVEN ids from a workstation (including muse-spark-1.3-contributor) but only
# FOUR from inside the hive pod — so the rung shipped as 1.2-contributor, the
# only CONTRIBUTOR tier in both catalogs, after 1.3 failed in-cluster with
# "model `muse-spark-1.3-contributor` does not exist or you lack access".
# RESOLVED 2026-09-23: with the rotated META_API_KEY the pod's own catalog
# offers muse-spark-1.3-contributor (live-verified via kubectl exec from the
# hive pod), so the rung is 1.3-contributor. Lesson kept: re-check the pod's
# own catalog before promoting an id — never a laptop's.
#
# muse (Muse Code, provider pool `meta`) sits at T2 and T3, and that placement
# is MEASURED, not guessed. Artificial Analysis scores "Muse Spark 1.2 (xhigh)"
# (slug muse-spark-1-2) at agentic index 44.2, which on the SAME scale the live
# tier cache uses puts it between claude-sonnet-5 (44.5) and gpt-5-6-luna
# (42.9) — i.e. the second-strongest T2 rung, not a T3 one. It was parked at T3
# only while that number was unknown.
#
# TWO CAVEATS, both worth keeping:
#   - The 44.2 is for the XHIGH reasoning-effort variant. muse's own default is
#     `high`, so a rung launched without --reasoning-effort xhigh is not the
#     thing AA measured and should be expected to score somewhat lower. The
#     TIERS format has no effort column, so this cannot be expressed here yet.
#   - AA scored the bare `muse-spark-1.2`; hive runs `muse-spark-1.3-contributor`.
#     Same generation family, differing in entitlement/billing tier (contributor)
#     and minor version (1.3 ahead of 1.2 on every vendor number), so the 44.2
#     floor is taken to carry over a fortiori — but it is an inference, not a
#     measurement of the exact id we run. A 1.3 AA score, if one appears, should
#     replace this reasoning, not confirm it.
#
# It is placed LAST within T2 on purpose. Order within a tier is preference, so
# every measured incumbent still wins whenever it has headroom; muse is reached
# only when they do not. `meta` is its own provider pool so an exhausted or
# failed Meta account can never wedge rotation off anthropic/openai/google.
#
# Format: tier|provider|backend|model   (order within a tier = preference)
# Double-quoted so the two rung variables above expand; the block contains no
# other `$`, so nothing else is interpolated.
# KIRO RUNGS (2026-09-24). The owner's Kiro Power plan: 10000 credits per
# calendar month, overage DISABLED (a hard stop at 100%), usage readable via
# GetUsageLimits (see probe_all). Reached through the `pi` backend, so the model
# id carries pi's provider prefix. Credits per request scale with the model's
# rateMultiplier from ListAvailableModels:
#     claude-opus-5 2.2   claude-sonnet-5 1.3   claude-haiku-4-5 0.4
#     gpt-5.6-sol 4.4     gpt-5.6-terra 2.2     gpt-5.6-luna 1.1
# Same frontier models as the claude/codex rungs (TB2.1: sol 89.5, opus-5 89.1,
# luna 75.7, sonnet-5 74.6 — measured under their own CLIs; under pi they are
# expected to be comparable, not yet measured). Two rungs per tier so the
# operator can spread model families; the Claude one is listed first because
# it is half the credits of its GPT peer at T1.
#
# EVERY KIRO RUNG CARRIES A pi THINKING SUFFIX (`:high` / `:medium` / `:low`),
# and that is load-bearing, not style. v5's normalizeModelNameForBackend (the
# copilot-era "dots in version" rewrite, manager_routing.go) turns a trailing
# `-<digits>` into `.<digits>` for every backend except claude/bob, so
# `kiro-api-key/claude-opus-5` launched as `pi --model kiro-api-key/claude-opus.5`
# — an unknown id pi passes through as custom (observed 2026-09-24, hanthor
# architect). pi's `provider/id:<thinking>` syntax ends the id in a non-digit, so
# v5 leaves it alone, and it pins the reasoning level explicitly.
TIERS="
T1|google|agy|gemini-3.8-flash-high
T1|kiro|pi|kiro-api-key/claude-opus-5:high
T1|kiro|pi|kiro-api-key/gpt-5-6-sol:high
T1|openai|codex|gpt-5.6-sol
T1|anthropic|claude|$T1_ANTHROPIC_MODEL
T2|google|agy|gemini-3.8-flash-low
T2|kiro|pi|kiro-api-key/claude-sonnet-5:medium
T2|kiro|pi|kiro-api-key/gpt-5-6-luna:medium
T2|openai|codex|gpt-5.6-luna
T2|anthropic|claude|$T2_ANTHROPIC_MODEL
T2|google|agy|gemini-3.6-flash-low
T2|meta|muse|$META_MODEL
T3|google|agy|gemini-3.8-flash-low
T3|kiro|pi|kiro-api-key/claude-haiku-4-5:low
T3|openai|codex|gpt-5.6-luna
T3|anthropic|claude|claude-haiku-4-5-20251001
T3|google|agy|gemini-3.6-flash-low
T3|meta|muse|$META_MODEL
"

# Agent -> required capability tier. Cadence is the cost lever (the governor
# already fixes it); tier is the competence floor. supervisor+scanner are ~83%
# of all kick volume, so they sit on the cheapest adequate rung — which on these
# numbers is also a near-frontier one.
AGENT_TIERS='
supervisor|T2
scanner|T2
ci-maintainer|T2
quality|T2
guide|T2
outreach|T2
sec-check|T1
architect|T1
strategist|T1
operations|T2
telemetry|T2
'
# operations/telemetry are ACMM-pack-injected (not in hive.yaml — the pack
# "overrides backends to copilot" per the config comment) and were previously
# absent from this table entirely, so tier_of() returned empty and every
# rotation/healing path silently skipped them (`[ -z "$tier" ] && continue`).
# Combined with copilot's device-flow login being unautomatable and unmodeled
# in TIERS (no github|copilot rung exists — intentionally, see provider_of),
# that left them permanently stuck the moment copilot needed re-auth: kicked
# every 5min by the watchdog, never rotated, never producing. 2026-09-02.

tier_of() { printf '%s\n' "$AGENT_TIERS" | awk -F'|' -v a="$1" '$1==a{print $2}'; }

# Prefer the LIVE tier cache generated by hive-tiers.sh from the Artificial
# Analysis Data API; fall back to the built-in TIERS table above when the cache
# is missing or stale. A benchmark-API outage must never wedge rotation, so the
# fallback is a feature, not a safety net nobody exercises.
TIER_CACHE="$STATE_DIR/tiers.tsv"
TIER_MAX_AGE_DAYS="${HIVE_TIERS_MAX_AGE_DAYS:-14}"
TIER_SOURCE=builtin
if [ -s "$TIER_CACHE" ] && [ -n "$(find "$TIER_CACHE" -mtime "-$TIER_MAX_AGE_DAYS" 2>/dev/null)" ]; then
  TIER_SOURCE=api
fi

# Live model inventory (hive-inventory.sh). A rung naming a model the backend
# does not actually offer is not a config typo you find later — it launches an
# agent that immediately dies, which reads as a dead agent rather than a bad
# id. Measured 2026-09-03, the built-in table carried three of them:
# claude-haiku-4-5 (real id claude-haiku-4-5-20251001), deepseek-chat (absent
# from DeepSeek's list), gemini-3.6-flash (real ids are -high/-medium/-low).
INVENTORY="$STATE_DIR/inventory.tsv"
INVENTORY_MAX_AGE_DAYS="${HIVE_INVENTORY_MAX_AGE_DAYS:-3}"
INVENTORY_OK=0
if [ -s "$INVENTORY" ] && [ -n "$(find "$INVENTORY" -mtime "-$INVENTORY_MAX_AGE_DAYS" 2>/dev/null)" ]; then
  INVENTORY_OK=1
fi

# tier_members <tier>: the rungs for a tier, filtered to models that actually
# exist.
#
# The filter is SCOPED PER PROVIDER, and that is the whole trick. openai has no
# list endpoint (codex authenticates by subscription), so it contributes zero
# inventory rows; a naive "drop anything not in the inventory" would delete
# every codex rung and silently remove a whole provider from the ladder. So a
# rung is dropped only when its provider WAS successfully inventoried and the
# model is still absent. A provider we could not measure keeps all its rungs —
# unmeasured is not evidence of absence, the same rule provider_ok uses.
#
# Fails open on a missing or stale inventory: the ladder is better slightly
# wrong than empty, and an inventory outage must never wedge rotation.
tier_members() {
  local raw builtin
  builtin=$(printf '%s\n' "$TIERS" | awk -F'|' -v t="$1" '$1==t{print}')
  if [ "$TIER_SOURCE" = api ]; then
    raw=$(awk -F'\t' -v t="$1" '!/^#/ && $1==t {print $1"|"$2"|"$3"|"$4}' "$TIER_CACHE")
    # UNION, not replace. The benchmark feed does not cover every provider this
    # fleet runs: measured 2026-09-06, Artificial Analysis scored ZERO DeepSeek
    # models and only two Google ones (both -3.5, neither a rung we use), while
    # DeepSeek is the DEFAULT rung on both cost and capability per the table
    # above. Letting the cache REPLACE the table therefore deleted deepseek and
    # google from the ladder entirely the moment a refresh succeeded — the
    # cheapest and most-used provider silently disappearing because a
    # third-party benchmark had not gotten to it.
    #
    # So: take every cache row, then add every built-in row whose provider+model
    # the cache does not already carry. Same rule the inventory gate below uses —
    # unmeasured is not evidence of absence.
    #
    # De-dupe on provider+MODEL, not provider alone. Scoring a provider is not
    # the same as scoring the rungs we run: the feed scores google
    # gemini-3-5-flash, while `agy models` offers 3.8/3.7/3.6/3.1 and nothing
    # else. Dropping the built-in google rungs just because google appeared in
    # the feed would leave google with one rung naming a model the CLI does not
    # have — which the inventory gate then filters out, leaving google with NO
    # rungs at all. Unioning per-model keeps the real rungs and still lets the
    # feed introduce genuinely new ones.
    # Cache rows are fed in FIRST, so first-wins on provider|model keeps the
    # feed-ranked rung and discards only the built-in duplicate of it.
    raw=$(printf '%s\n%s\n' "$raw" "$builtin" | awk -F'|' '
      NF < 4 { next }
      { if (!emitted[$2 "|" $4]++) print }
    ')
  else
    raw=$builtin
  fi

  # ── ENTITLEMENT GATE: not all of muse's catalog is ours to run ──────────
  #
  # GET https://api.meta.ai/v1/models returns seven ids. Only the
  # `-contributor` tiers are the ones this fleet is entitled to:
  #
  #   muse-spark-1.3-contributor, muse-spark-1.2-contributor   <- ours
  #   muse-spark-1.3, muse-spark-1.2, muse-spark-1.1           <- NOT ours
  #   muse-voice-transcribe-1.0, muse-image-1.0                <- not coding models
  #
  # This must be a GATE rather than just careful authoring of TIERS above,
  # because the built-in table is only ONE of two sources. tier_members unions
  # in the Artificial Analysis cache, so the day `meta` is added to
  # hive-tiers.sh's creator map the feed can introduce bare `muse-spark-*`
  # rungs that nothing else in this script would reject.
  #
  # And muse will NOT stop us. Measured 2026-09-08 against 1.0.3: the
  # non-contributor ids run perfectly happily (`muse exec --model
  # muse-spark-1.3` exits 0 and answers), so there is no natural failure to
  # catch — the only symptom would be billing against a tier we did not mean
  # to use. Worse, muse does not reliably reject even a WHOLLY INVALID id:
  # `--model definitely-not-a-model` exited 0 and answered normally for the
  # prompt "hi" (3/3 trials) while exiting 1 for the prompt "say ok". A bad
  # rung can therefore pass a trivial smoke test and only fail on real work,
  # which is precisely the failure this gate has to prevent rather than detect.
  #
  # Fails CLOSED for muse specifically — an unrecognised muse model is dropped,
  # not passed through — which is the opposite of the inventory gate's
  # fail-open rule below, and deliberately so: fail-open there protects a
  # provider we could not measure, whereas here the risk is spending on a tier
  # we are not entitled to. Every other backend is untouched.
  raw=$(printf '%s\n' "$raw" | awk -F'|' '
    NF < 4        { next }
    $3 != "muse"  { print; next }
    $4 ~ /-contributor$/ { print }
  ')

  [ "$INVENTORY_OK" = 1 ] || { printf '%s\n' "$raw"; return; }
  printf '%s\n' "$raw" | awk -F'|' -v inv="$INVENTORY" '
    BEGIN {
      while ((getline line < inv) > 0) {
        if (line ~ /^#/) continue
        split(line, f, "\t")
        if (f[1] == "") continue
        have[f[1] "|" f[3]] = 1      # provider|model_id
        measured[f[1]] = 1           # provider was inventoried at all
      }
    }
    NF < 4 { next }
    # A pi `:<thinking>` suffix is launch syntax, not part of the model id.
    { m = $4; sub(/:(off|minimal|low|medium|high|xhigh|max)$/, "", m)
      if (!measured[$2] || have[$2 "|" m]) print }
  '
}

# ── Pod + owner session + status snapshot ───────────────────────────────
# hive_open (hive-lib.sh) sets POD, SID and STATUS_JSON: the owner session
# cookie comes from the pod's own store (cached; a refused cookie is re-read),
# and STATUS_JSON is the SLIM /api/status (v5's full one is ~3 MB). Taken ONCE
# per run; every decision below reads from it.
#
# STALENESS: /api/status lags a mutation by more than 10s — a switch/model_set
# applied immediately before this fetch may still report the OLD rung. On the
# intended cadence this is a non-issue, and the failure mode is benign: a
# stale read causes a MISSED correction on this tick, never a wrong mutation.
# Do not chain apply runs.
hive_open "$NS" || { echo "ERROR: could not read /api/status from $NS" >&2; exit 1; }

# hive_api <METHOD> <path> [max_time] — via the hive Service in-cluster, via
# exec from a workstation. Always prints JSON (transport failures are wrapped
# as {"ok":false,"error":...}), so `jq -r '.status // .error'` is always safe.
hive_api() { hive_call "$NS" "$POD" "$SID" "$1" "$2" "${3:-}"; }

# Field lookups come from an associative array filled by ONE jq pass. Each
# jq/fork costs ~1 s at the hive node's load (~85 on 4 vCPU), and the old
# per-call `jq` ran ~130 times per watchdog pass. Semantics are unchanged:
# `.[f] // ""` (so false/null read as ""). Multi-line fields (liveSummary,
# statusEvidence) are still read with jq on demand.
declare -A AF
while IFS=$'\t' read -r _n _k _v; do AF["$_n|$_k"]=$_v; done < <(
  printf '%s' "$STATUS_JSON" | jq -r '.agents[] | .name as $n | to_entries[]
    | select(.key != "liveSummary" and .key != "statusEvidence")
    | select((.value | type) != "object" and (.value | type) != "array")
    | [$n, .key, (.value // "" | tostring)] | @tsv')
AGENT_NAMES=$(printf '%s' "$STATUS_JSON" | jq -r '.agents[].name')
agent_field() {
  if [ -n "${AF["$1|$2"]+x}" ]; then printf '%s' "${AF["$1|$2"]}"
  else printf '%s' "$STATUS_JSON" | jq -r --arg a "$1" --arg f "$2" '.agents[]|select(.name==$a)|.[$f]//""'; fi
}
agent_names() { printf '%s\n' "$AGENT_NAMES"; }

# Placement pins must be available to both the watchdog and the apply path.
# The watchdog exits before the apply-only declarations near the bottom.
PIN=",$(printf '%s' "${HIVE_ROTATE_PIN:-}" | tr -d '[:space:]'),"
pinned() { [ "$PIN" != ",," ] && [ "${PIN#*,$1,}" != "$PIN" ]; }

# provider_of <backend> <model> -> the account an agent draws on (hive-lib.sh).
provider_of() { hive_provider_of "$1" "$2"; }

# A paused login-detector agent makes its provider unmeasurable: the pane probe
# skips paused agents and returns "no-agent". That is positive evidence of a
# provider outage, unlike an ordinary unknown/no-agent result.
declare -A LOGIN_BLOCKED
for a in $(agent_names); do
  if [ "$(agent_field "$a" paused)" = true ] &&
     [ "$(agent_field "$a" pausedTrigger)" = login-detector ]; then
    p=$(provider_of "$(agent_field "$a" cli)" "$(agent_field "$a" govModel)")
    [ -n "$p" ] && LOGIN_BLOCKED[$p]=1
  fi
done

provider_login_blocked() { [ "${LOGIN_BLOCKED[$1]:-0}" = 1 ]; }

# backend_model_mismatch <backend> <model>: 0 when the pair CANNOT launch.
#
# Placement is two API calls (/api/switch then /api/model) with no transaction
# around them. When the second fails — and it does, the dashboard API times out
# under concurrent mutations — the agent is left on the NEW backend with the
# OLD model, e.g. `claude --model gemini-3.8-flash-low`. That is a hard startup
# failure: the pane dies, the watchdog sees a bare shell, and it churns forever.
# The script already guarded the mirror case (switch fails, model succeeds); it
# did not guard this one, which is the one that actually kept happening.
#
# Only SINGLE-PROVIDER CLIs are judged. pi/goose/litellm are shells over a
# configurable provider (the contributor legitimately runs pi with
# openai-codex/gpt-5.6-sol), so a "foreign" model name there is not evidence of
# anything and must not be touched.
backend_model_mismatch() {
  local b="$1" m="$2"
  [ -z "$b" ] || [ -z "$m" ] && return 1
  case "$b" in
    claude) case "$m" in *claude*|*opus*|*sonnet*|*haiku*) return 1 ;; *) return 0 ;; esac ;;
    agy)    case "$m" in *gemini*) return 1 ;; *) return 0 ;; esac ;;
    codex)  case "$m" in *gpt-*|*codex*) return 1 ;; *) return 0 ;; esac ;;
    # pi's only provider in this fleet is Kiro now (its old deepseek default is
    # gone), so a pi agent on any non-kiro model cannot launch — typically the
    # half-placed `pi --model gemini-…` left when /api/model failed after
    # /api/switch.
    pi)     case "$m" in kiro-api-key/*) return 1 ;; *) return 0 ;; esac ;;
    *)      return 1 ;;
  esac
}

# repair_mismatch <agent>: put a mismatched agent back on a model its CURRENT
# backend can actually run, preferring its own tier's rung for that backend.
repair_mismatch() {
  # A pinned agent's pair is the operator's, not the ladder's. Without this the
  # watchdog "repairs" a deliberate pin back to a tier member within 5 minutes —
  # supervisor on gpt-5.4-mini (unmetered, deliberately off-ladder) would be
  # rewritten to the T2 codex rung. Repair only ever picks a TIER member, so it
  # can never restore a pin; skipping is the only correct answer here.
  if pinned "$1"; then return 1; fi
  local a="$1" b m tier want
  b=$(agent_field "$a" cli); m=$(agent_field "$a" govModel)
  backend_model_mismatch "$b" "$m" || return 1
  tier=$(tier_of "$a"); [ -z "$tier" ] && return 1
  want=$(tier_members "$tier" | awk -F'|' -v b="$b" '$3==b{print $4; exit}')
  [ -z "$want" ] && return 1
  printf '%-14s MISMATCH %s/%s -> setting model %s\n' "$a" "$b" "$m" "$want"
  dry && return 0
  local md; md=$(hive_api POST "/api/model/$a/$(hive_model_path "$want")" | jq -r '.status // .error')
  if [ "$md" = "model_set" ]; then sync_effort "$a" "$b" "$want"
  else printf '    ! repair failed: %s\n' "$md"; fi
}

# dry: true when this run must not mutate anything (plan, or a dry-run watchdog).
dry() { [ "$ACTION" = plan ] || [ "${HIVE_ROTATE_DRYRUN:-0}" = 1 ]; }

# ── Reasoning effort (v5) ───────────────────────────────────────────────
# v5 launches agy with `--effort <agent effort>` (default low), and agy drops a
# suffixed model whose suffix disagrees — "--model gemini-3.8-flash-high
# conflicts with --effort=low. Using Gemini 3.6 Flash (Low) instead." Every
# placement on an agy rung therefore also sets the matching effort via
# POST /api/effort/{agent}/{effort}. The effort is not exposed in /api/status,
# so what we last set is recorded per agent; "" means never set = v5 default.
EFFORT_DIR="${HIVE_EFFORT_DIR:-$STATE_DIR/effort}"
effort_recorded() { cat "$EFFORT_DIR/$1" 2>/dev/null; }

# sync_effort <agent> <backend> <model>: set the effort the model needs, if any.
sync_effort() {
  local a="$1" b="$2" m="$3" want rs
  want=$(effort_change "$b" "$m" "$(effort_recorded "$a")")
  [ -n "$want" ] || return 0
  printf '%-14s EFFORT %s needs --effort %s -> setting\n' "$a" "$m" "$want"
  dry && return 0
  rs=$(hive_api POST "/api/effort/$a/$want" | jq -r '.status // .error')
  if [ "$rs" = effort_set ]; then
    mkdir -p "$EFFORT_DIR" && echo "$want" > "$EFFORT_DIR/$a"
  else
    printf '    ! effort set failed: %s\n' "$rs"
  fi
}

# place_agent <agent> <backend> <model>: switch (only if the backend changes),
# set the model, then the effort. Returns 0 only when the agent ended on the
# requested pair. Never leaves a new backend with the old backend's model —
# `claude --model gemini-...` cannot launch — so a failed model set rolls the
# backend back.
place_agent() {
  local a="$1" wb="$2" wm="$3" curb sw md rb
  curb=$(agent_field "$a" cli)
  if [ "$wb" != "$curb" ]; then
    sw=$(hive_api POST "/api/switch/$a/$wb" | jq -r '.status // .error')
    if [ "$sw" != switched ]; then echo "    ! switch failed: $sw — leaving $a alone"; return 1; fi
  fi
  md=$(hive_api POST "/api/model/$a/$(hive_model_path "$wm")" | jq -r '.status // .error')
  if [ "$md" != model_set ]; then
    if [ "$wb" != "$curb" ]; then
      rb=$(hive_api POST "/api/switch/$a/$curb" | jq -r '.status // .error')
      echo "    ! model set failed: $md — rolled back to $curb ($rb)"
    else
      echo "    ! model set failed: $md"
    fi
    return 1
  fi
  sync_effort "$a" "$wb" "$wm"
  return 0
}


# ── Probes ──────────────────────────────────────────────────────────────
# Each provider reduces to "<pct_used> <note>" — pct_used 0-100, or -1 if
# unknown.
#
# ONE EXEC, ALL PROVIDERS, IN PARALLEL (2026-09-24). The old probes were one
# `kubectl exec` each (the google one several: pick an agent, check its pane,
# look up its uid...), run serially, and the openai fallback TYPED `/status`
# into a live agent's TUI and slept 16 s. Each exec cost 2-4.5 s before any
# work, so gather() alone blew a 600 s deadline once a couple of probes
# stalled. Now a single in-pod script runs every probe concurrently, each under
# its own `timeout`, and returns the raw bodies; all parsing happens here, in
# pure functions (parse_probe_*) that are unit-tested.
#
# Credentials never cross the exec boundary: the in-pod script reads the API
# keys / OAuth token itself and only response bodies come back.
#
# The pane-typing /status fallback for openai is GONE: it was the slowest and
# riskiest step (keystrokes into a working agent), and `codex app-server`'s
# account/rateLimits/read is the structured source. A stale "hit your usage
# limit" banner is still honoured, read from /api/status liveSummary.

# probe_all <agent-to-run-agy-as>: raw bodies, one "=====HIVE-PROBE <p>"
# section per provider.
probe_all() {
  # shellcheck disable=SC2016
  timeout "${HIVE_PROBE_TIMEOUT:-150}" kubectl exec -n "$NS" "$POD" -- sh -c '
    A="$1"; T=$(mktemp -d /tmp/hive-probe.XXXXXX)
    u=$(id -u "hive-$A" 2>/dev/null || getent passwd | awk -F: "/^hive-/{print \$3; exit}")
    ( if [ -n "${KIRO_API_KEY:-}" ]; then
        timeout 25 curl -sS --max-time 20 -X POST https://q.us-east-1.amazonaws.com/ \
          -H "Authorization: Bearer $KIRO_API_KEY" -H "tokentype: API_KEY" \
          -H "Content-Type: application/x-amz-json-1.0" -H "Accept: application/json" \
          -H "X-Amz-Target: AmazonCodeWhispererService.GetUsageLimits" \
          -H "x-amzn-codewhisperer-optout: true" \
          -H "user-agent: aws-sdk-rust/1.0.0 ua/2.1 os/other lang/rust api/codewhispererruntime#1.28.3 m/E app/AmazonQ-For-CLI" \
          -d "{\"origin\":\"AI_EDITOR\",\"resourceType\":\"AGENTIC_REQUEST\"}"
      else echo KIRO-KEY-MISSING; fi > "$T/kiro" 2>&1 ) &
    ( timeout 25 curl -sS --max-time 20 -H "Authorization: Bearer $META_API_KEY" \
        https://api.meta.ai/v1/models > "$T/meta" 2>&1 ) &
    ( timeout 25 su-exec "$u" sh -c "
        TOK=\$(jq -r \".claudeAiOauth.accessToken // empty\" /data/home/.claude/.credentials.json 2>/dev/null)
        [ -z \"\$TOK\" ] && { echo \"-1 no-token\"; exit 0; }
        curl -s --max-time 15 -H \"Authorization: Bearer \$TOK\" \
             -H \"anthropic-beta: oauth-2025-04-20\" https://api.anthropic.com/api/oauth/usage" \
        > "$T/anthropic" 2>/dev/null ) &
    ( { printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":0,\"method\":\"initialize\",\"params\":{\"clientInfo\":{\"name\":\"hive-rotate\",\"version\":\"1.0.0\",\"title\":\"hive-rotate\"}}}"
        sleep 4
        printf "%s\n" "{\"jsonrpc\":\"2.0\",\"method\":\"initialized\"}"
        printf "%s\n" "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"account/rateLimits/read\",\"params\":{}}"
        sleep 14
      } | HOME=/data/home timeout 40 codex app-server > "$T/openai" 2>/dev/null ) &
    ( if command -v agy >/dev/null 2>&1; then
        timeout 90 su -s /bin/sh "hive-$A" -c "HOME=/data/home agy --print /usage --output-format text" \
          > "$T/google" 2>/dev/null
      else echo AGY-BINARY-MISSING > "$T/google"; fi ) &
    wait
    for p in kiro meta anthropic openai google; do
      echo "=====HIVE-PROBE $p"; cat "$T/$p" 2>/dev/null; echo
    done
    rm -rf "$T"' sh "$1" 2>/dev/null
}

# probe_section <all-output> <provider>: that provider's raw body.
probe_section() {
  printf '%s\n' "$1" | awk -v p="$2" '
    /^=====HIVE-PROBE / { on = ($2 == p); next }
    on { print }'
}

# Kiro GetUsageLimits (AmazonCodeWhispererService, same endpoint and bearer
# key as the pi provider; found 2026-09-24 — the Kiro IDE's own usage call).
# Answer: usageBreakdownList[] with resourceType CREDIT, currentUsageWithPrecision
# / usageLimitWithPrecision (10000 on Power), nextDateReset (epoch; the 1st of
# the month 00:00Z), and overageConfiguration.overageStatus. With overage
# DISABLED the plan hard-stops at 100%, so it is exhaustion like any cap; with
# overage ENABLED every credit past the limit is billed ($0.04), so the reading
# is flagged and the threshold still keeps the fleet off it.
# credits=U/L is carried in the note so the pacer can fit sub-percent burn.
parse_probe_kiro() {  # stdin: GetUsageLimits body
  local out
  out=$(cat)
  case "$out" in KIRO-KEY-MISSING*) echo "-1 no-key (KIRO_API_KEY not in the hive pod env)"; return ;; esac
  printf '%s' "$out" | jq -r '
    ([.usageBreakdownList[]? | select(.resourceType == "CREDIT")] | first) as $u
    | if $u == null or ($u.usageLimitWithPrecision // 0) <= 0 then empty else
        ($u.currentUsageWithPrecision / $u.usageLimitWithPrecision * 100) as $p
        | "\([($p | floor), 100] | min) credits=\($u.currentUsageWithPrecision + 0)/\($u.usageLimitWithPrecision + 0)"
          + " resets=\(((.nextDateReset // $u.nextDateReset) | floor | todate))"
          + (if (.overageConfiguration.overageStatus // "") == "ENABLED" then " overage=ENABLED" else "" end)
      end' 2>/dev/null | grep . \
    || { if printf '%s' "$out" | grep -qi 'AccessDenied\|invalid'; then echo "100 key-rejected"
         else echo "-1 unparsed"; fi; }
}

# muse has NO usage/quota endpoint. What can be checked: the credential works
# AND the exact rung rotation would place is in THIS CALLER's catalog (muse's
# catalog is caller-dependent). 100 = stay off; -1/no-usage-api = reachable,
# entitled, quota unknowable.
parse_probe_meta() {  # stdin: /v1/models body
  local out
  out=$(cat)
  printf '%s' "$out" | jq -e '.data' >/dev/null 2>&1 \
    || { echo "100 unreachable-or-bad-credential"; return; }
  if printf '%s' "$out" | jq -e --arg m "$META_MODEL" '.data[]|select(.id==$m)' >/dev/null 2>&1; then
    echo "-1 no-usage-api"
  else
    echo "100 ${META_MODEL} not offered to this caller"
  fi
}

# Anthropic OAuth usage API. Only UNSCOPED limits describe the provider — a
# weekly_scoped{model:"Fable"} at 100% caps one model class, not the account
# (taking the max across all three parked the fleet on 2026-09-02 while Sonnet
# answered). The full unscoped limit set is written to $2 for the pacer.
# An EMPTY credential is positive evidence the provider cannot serve (Claude
# Code zeroes the file when a refresh fails) — 100, "needs /login".
parse_probe_anthropic() {  # stdin: usage body; $1: limits file to write
  local out pct r capped
  out=$(cat)
  case "$out" in
    -1\ no-token*) echo "100 no-credential (needs an interactive /login)"; return ;;
  esac
  if [ -n "${1:-}" ]; then
    printf '%s' "$out" | jq -c 'try ([.limits[]? | select(.scope == null and .percent != null)]
          | sort_by(.resets_at)
          | to_entries | map({slot:"slot\(.key)", percent:.value.percent, resets_at:.value.resets_at}))
          // empty' > "$1.tmp" 2>/dev/null
    # Never overwrite a good limit set with an empty one (a 429 body parses to
    # [] and blinded the pacer).
    if [ -s "$1.tmp" ] && [ "$(cat "$1.tmp")" != "[]" ]; then mv "$1.tmp" "$1"; else rm -f "$1.tmp"; fi
  fi
  pct=$(printf '%s' "$out" | jq -r 'try ([.limits[]? | select(.scope == null) | .percent // 0] | max) // empty' 2>/dev/null)
  r=$(printf '%s' "$out" | jq -r 'try ([.limits[]? | select(.scope == null and .percent != null)] | max_by(.percent) | .resets_at) // empty' 2>/dev/null)
  capped=$(printf '%s' "$out" | jq -r 'try ([.limits[]? | select(.scope != null and .percent >= 100) | .scope.model.display_name] | join(",")) // empty' 2>/dev/null)
  if [ -z "$pct" ] || [ "$pct" = null ]; then
    if printf '%s' "$out" | grep -q 'rate_limit'; then echo "-1 rate-limited"
    else echo "-1 unparsed"; fi   # fail-open, never act on it
  else
    printf '%s resets=%s%s\n' "$pct" "$r" "${capped:+ capped-models=$capped}"
  fi
}

# codex app-server account/rateLimits/read: up to two windows (primary /
# secondary), each {usedPercent, windowDurationMins, resetsAt}. Take the WORSE
# one — either stalls the agent — and carry its reset so the watchdog can wake
# the fleet at renewal. Label windows by their real duration: on this account
# `primary` is the WEEKLY window (10080 min), which the old "codex-5h=" label
# misreported. The handshake needs the `initialized` notification and ~15 s;
# with 8 s and no notification it answered only some of the time.
parse_probe_openai() {  # stdin: app-server JSON-RPC lines
  local out
  out=$(jq -r 'select(.id==2) | .result.rateLimits
         | [.primary, .secondary] | map(select(. != null and .usedPercent != null))
         | if length == 0 then empty else
             (max_by(.usedPercent)) as $b
             | "\($b.usedPercent) "
               + (map((if (.windowDurationMins // 0) >= 1440 then "weekly"
                       elif .windowDurationMins then "\(.windowDurationMins / 60 | floor)h"
                       else "window" end) + "=\(.usedPercent)%") | join(" "))
               + (if $b.resetsAt then " resets=\($b.resetsAt | todate)" else "" end)
           end' 2>/dev/null | head -1)
  [ -n "$out" ] && { echo "$out"; return; }
  echo "-1 unparsed"
}

# agy `--print /usage` rows. Only "Gemini Models" rows bind this backend; take
# the lower of weekly / five-hour remaining.
parse_probe_google() {  # stdin: agy /usage text
  local out
  out=$(cat)
  case "$out" in AGY-BINARY-MISSING*) echo "-1 agy-binary-missing"; return ;; esac
  printf '%s\n' "$out" | awk '
    /^Gemini Models/ {
      if (match($0, /[0-9]+%/)) { pct = substr($0, RSTART, RLENGTH-1) }
      if (match($0, /[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z/)) { r = substr($0, RSTART, RLENGTH) }
      if (pct != "" && (best == "" || pct+0 < best+0)) { best = pct; bestr = r }
      pct = ""; r = ""
    }
    END { if (best == "") print "-1 unparsed"; else print (100-best)" resets="bestr }'
}

# openai fallback: a HARD account cap is announced in the pane itself
# ("You've hit your usage limit ... try again at ..."). Positive evidence, read
# from the hive's own pane capture instead of typing into the TUI.
openai_pane_cap() {
  local a text when
  for a in $(agent_names); do
    [ "$(provider_of "$(agent_field "$a" cli)" "$(agent_field "$a" govModel)")" = openai ] || continue
    text=$(agent_field "$a" liveSummary)
    if printf '%s' "$text" | grep -qiE "hit your usage limit|usage limit reached|out of credits"; then
      when=$(printf '%s' "$text" | grep -oiE 'try again at [^.]*' | head -1)
      echo "100 ${when:-account limit reached}"
      return
    fi
  done
}

first_agent_on() {  # provider -> name of a RUNNING agent currently on it
  local p="$1" n b m
  for n in $(agent_names); do
    [ "$(agent_field "$n" paused)" = "true" ] && continue
    b=$(agent_field "$n" cli); m=$(agent_field "$n" govModel)
    [ "$(provider_of "$b" "$m")" = "$p" ] && { echo "$n"; return; }
  done
}

in_peak_window() {
  # DeepSeek peak pricing applies WEEKDAYS ONLY since 2026-08-23 (Beijing
  # time); weekends are all-day off-peak. PEAK_WINDOWS are 01:00-10:00 UTC, and
  # at those hours Beijing is UTC+8 on the SAME calendar date, so the UTC
  # weekday IS the Beijing weekday — gate directly on it.
  local dow; dow=$(date -u +%u)   # 1=Mon .. 7=Sun
  [ "$dow" -gt 5 ] && return 1   # Sat/Sun: all-day off-peak, never in window
  local now win start end; now=$(date -u +%H:%M)
  IFS=, read -ra WINS <<< "$PEAK_WINDOWS"
  for win in "${WINS[@]}"; do
    start=${win%%-*}; end=${win##*-}
    if [[ "$start" < "$end" ]]; then
      [[ "$now" > "$start" || "$now" == "$start" ]] && [[ "$now" < "$end" ]] && return 0
    else  # window wraps midnight
      [[ "$now" > "$start" || "$now" < "$end" ]] && return 0
    fi
  done
  return 1
}


# ── Gather headroom ─────────────────────────────────────────────────────
declare -A PCT NOTE
# The provider pools this fleet measures and places on. Written ONCE (adding a
# provider to only some loops left it with no note, which provider_ok rejects).
PROVIDERS="${HIVE_ROTATE_PROVIDERS:-kiro anthropic openai google meta}"

# Where the measurement is published. ALWAYS the primary hive's namespace:
# every spoke draws on the SAME accounts (the .claude/.gemini/.codex homes are
# one hostPath and the API keys hash identically across hive, hive-reef and
# hive-hanthor, verified 2026-09-24), and the spoke Roles cannot write
# ConfigMaps in their own namespaces anyway ("WARN: could not publish").
USAGE_NS="${HIVE_PRIMARY_NS:-hive}"
USAGE_CM=hive-provider-usage

# USAGE REUSE. Three rotates (every 20 min) and three watchdogs (every 5 min)
# each probed every provider — ~40 hits/hour on api.anthropic.com's OAuth usage
# endpoint, which rate-limits a second poller within minutes and then reports
# `unparsed` for EVERYONE (observed again 2026-09-24: anthropic "unknown
# unparsed" fleet-wide). Since the accounts are shared, one fresh measurement
# serves every spoke:
#   - primary-hive apply/plan/probe: always measure, then publish;
#   - spoke apply/plan: reuse a publication younger than 20 min, else measure;
#   - watchdog (any hive): reuse anything younger than 30 min, else measure.
# HIVE_USAGE_MAX_AGE_S overrides (0 = always measure).
if [ -n "${HIVE_USAGE_MAX_AGE_S:-}" ]; then USAGE_MAX_AGE="$HIVE_USAGE_MAX_AGE_S"
elif [ "$ACTION" = probe ]; then USAGE_MAX_AGE=0
elif [ "$ACTION" = watchdog ]; then USAGE_MAX_AGE=1800
elif [ "$NS" = "$USAGE_NS" ]; then USAGE_MAX_AGE=0
else USAGE_MAX_AGE=1200
fi
MEASURED=0

load_published_usage() {
  local cm upd age p v
  [ "$USAGE_MAX_AGE" -gt 0 ] 2>/dev/null || return 1
  cm=$(k8s_get "/api/v1/namespaces/$USAGE_NS/configmaps/$USAGE_CM") || return 1
  upd=$(printf '%s' "$cm" | jq -r '.data.updated_at // empty')
  [ -n "$upd" ] || return 1
  age=$(( $(date -u +%s) - $(date -u -d "$upd" +%s 2>/dev/null || echo 0) ))
  [ "$age" -le "$USAGE_MAX_AGE" ] || return 1
  for p in $PROVIDERS; do
    v=$(printf '%s' "$cm" | jq -r --arg p "$p" '.data[$p] // "unknown unpublished"')
    r=$(published_to_probe "$v")
    PCT[$p]=${r%% *}; NOTE[$p]=${r#* }
  done
  echo "usage: reusing $USAGE_NS/$USAGE_CM published ${age}s ago"
  return 0
}

measure_usage() {
  local a raw p r
  # agy is headless; it only needs a uid with the shared $HOME. Prefer an agent
  # already on google, else any agent (paused or not — requiring an unpaused
  # one deadlocked the pool once everything was parked).
  a=$(first_agent_on google); [ -z "$a" ] && a=$(agent_names | head -1)
  raw=$(probe_all "$a")
  for p in $PROVIDERS; do
    case $p in
      kiro)      r=$(probe_section "$raw" kiro      | parse_probe_kiro) ;;
      meta)      r=$(probe_section "$raw" meta      | parse_probe_meta) ;;
      anthropic) r=$(probe_section "$raw" anthropic | parse_probe_anthropic "$STATE_DIR/anthropic-limits.json") ;;
      openai)    r=$(probe_section "$raw" openai    | parse_probe_openai)
                 if [ "${r%% *}" = -1 ]; then c=$(openai_pane_cap); [ -n "$c" ] && r=$c; fi ;;
      google)    r=$(probe_section "$raw" google    | parse_probe_google) ;;
      *)         r="-1 no-probe" ;;
    esac
    PCT[$p]=${r%% *}; NOTE[$p]=${r#* }
  done
  MEASURED=1
}

# publish_usage: mirror a FRESH measurement into $USAGE_NS/hive-provider-usage.
# Read by hive-pace, hive-console, and every other rotate/watchdog run (see
# USAGE REUSE above). Carries updated_at so a stale reading is visibly stale.
# Best-effort: a publish failure never affects rotation.
publish_usage() {
  local data p v lim=""
  [ "$MEASURED" = 1 ] || return 0
  dry && [ "$ACTION" != probe ] && return 0
  data='{}'
  for p in $PROVIDERS; do
    v="${PCT[$p]}"
    if [ "$v" = "-1" ]; then v="unknown"; else v="${v}% used"; fi
    data=$(printf '%s' "$data" | jq -c --arg k "$p" --arg v "$v ${NOTE[$p]}" '.[$k]=$v')
  done
  # Per-limit Anthropic detail for hive-pace.sh (which must never poll the
  # rate-limited usage API itself). Only a limit set measured in the last 30
  # min; a stale one would feed the pacer yesterday's deadlines.
  if [ -n "$(find "$STATE_DIR/anthropic-limits.json" -mmin -30 2>/dev/null)" ]; then
    lim=$(cat "$STATE_DIR/anthropic-limits.json")
  else
    lim=$(k8s_get "/api/v1/namespaces/$USAGE_NS/configmaps/$USAGE_CM" | jq -r '.data.anthropic_limits // empty' 2>/dev/null)
  fi
  data=$(printf '%s' "$data" | jq -c --arg lim "$lim" --arg u "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --arg by "$NS" \
           '. + {updated_at:$u, measured_by:$by} + (if $lim != "" then {anthropic_limits:$lim} else {} end)')
  k8s_put_cm "$USAGE_NS" "$USAGE_CM" "$data" || echo "WARN: could not publish $USAGE_NS/$USAGE_CM" >&2
}

gather() {
  local p when epoch
  load_published_usage || { measure_usage; publish_usage; }
  for p in $PROVIDERS; do
    # Remember WHEN an exhausted provider comes back, so the watchdog can wake
    # the fleet at renewal instead of on the next 20-minute tick. Best-effort.
    if provider_exhausted "$p"; then
      when=$(printf '%s' "${NOTE[$p]}" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}' | head -1)
      if [ -n "$when" ]; then
        epoch=$(date -u -d "$when" +%s 2>/dev/null)
        [ -n "$epoch" ] && { mkdir -p "$STATE_DIR/resets.d"; echo "$epoch" > "$STATE_DIR/resets.d/$p"; }
      fi
    else
      # No longer exhausted: nothing pending, so a stale stamp cannot re-fire.
      rm -f "$STATE_DIR/resets.d/$p" 2>/dev/null
    fi
  done

  # A peak-priced provider is "unavailable" for planning purposes even at 0% used.
  if in_peak_window; then
    for p in $PEAK_PROVIDERS; do
      [ "${PCT[$p]:-0}" -lt 100 ] 2>/dev/null && NOTE[$p]="${NOTE[$p]} +PEAK(avoid)"
      PEAK_NOW=1
    done
  fi
}

# ── Provider economics ──────────────────────────────────────────────────
# Providers are ranked by TRUE cost of running an agent there (lower is
# cheaper, preferred first). Nothing metered is left (DeepSeek, the only pool
# that burned prepaid money, was dropped 2026-09-24); every pool is a cap that
# resets for free, so the order is "most room, least shared" first.
#
#   google    (agy)     rank 0 — FREE. No money spend at all; the cap resets
#                                and is free again.
#   kiro      (pi)      rank 1 — Kiro Power: 10000 credits/month, used by no
#                                one else (not the operator's interactive CLI).
#                                The pool with the most headroom.
#   anthropic (claude)  rank 2 — subscription shared with the operator's own
#                                Claude Code and burning ~3x its allowance
#                                (2026-09-24): lean on it less.
#   openai    (codex)   rank 3 — subscription with a LOW limit, shared with the
#                                operator's own interactive CLI: protect it.
#
# Consequence: a high-cadence agent is barred ONLY from codex during normal
# operation (the pool most likely to strand the operator too). agy and claude
# are open to it — agy costs nothing and claude's cap is generous — each still
# subject to its own exhaustion threshold and the agy 5h-window cap below.
provider_cost_rank() {
  case "$1" in
    google)    echo 0 ;;
    kiro)      echo 1 ;;
    anthropic) echo 2 ;;
    openai)    echo 3 ;;
    *)         echo 4 ;;
  esac
}

# Kick-rate guard. Agents at or below this cadence (seconds) are "high volume"
# and are barred from the protected pool (codex) during normal operation.
# 1800s = 2 kicks/hour. The exception: a CONFIRMED exhausted current provider
# grants the controlled escape hatch passed by choose_rung — availability
# beats cost once the pool the agent was on has nothing left to protect.
HIGH_VOLUME_CADENCE_S="${HIVE_ROTATE_HIGH_VOLUME_S:-1800}"
METERED_EXHAUSTION_FAILOVER="${HIVE_ROTATE_METERED_FAILOVER:-1}"
# agy 5h-window stewardship: cap how many high-cadence agents may land on the
# free pool — its rolling five-hour limit is exactly what a 5m driver burns.
#
# Raised 2->5 on 2026-09-02. The old value silently assumed most agents were
# NOT high-volume. Once the surge cadences were tightened, every one of the 11
# agents fell under HIGH_VOLUME_CADENCE_S (30m), so the cap of 2 made 9 of them
# ineligible for the FREE pool and they all piled onto Anthropic — which burned
# a weekly subscription cap at ~10%/hour. Worse, it removed the failover floor:
# when Anthropic exhausts, choose_rung can seat only 2 agents on google and
# STRANDS (pauses) the rest, so the cheapest, most available provider cannot
# catch the fleet. A cap below the fleet size is a cap on failover capacity,
# not just on cost.
AGY_MAX_HIGH_VOLUME="${HIVE_ROTATE_AGY_MAX_HIGH_VOLUME:-5}"
# Watchdog: minimum minutes between auto-heal kicks of the same agent (the
# k8s CrashLoopBackOff analog; a fresh launch needs ~1min to reach ready).
# (Base of the exponential backoff in hive-lib.sh's watchdog_backoff_s; the
# old fixed-interval knob is honoured as the base.)
export HIVE_WATCHDOG_BASE_MIN="${HIVE_WATCHDOG_BASE_MIN:-${HIVE_WATCHDOG_KICK_INTERVAL_MIN:-5}}"
# How long a pool evicted because it measured exhausted stays canary-free.
# Defined here (not down by the canary section that reads/writes it) because
# the main rotation loop below also writes this cooldown file the moment it
# switches an agent off a provider it just found exhausted — under `set -u`
# that loop crashed mid-run on every first such switch, silently skipping
# every agent after it (confirmed 2026-09-02: guide switched off exhausted
# openai, then the run died before outreach/sec-check/strategist could be
# paused). CANARY_COOLDOWN_MIN stays defined only where it's used, since
# nothing outside the canary section reads it.
CANARY_EXHAUSTED_COOLDOWN_MIN="${HIVE_ROTATE_CANARY_EXHAUSTED_COOLDOWN_MIN:-720}"

cadence_s() { agent_field "$1" cadence \
                | awk '{ s=$0; n=s; sub(/[a-z]$/,"",n);
                         if (s ~ /h$/) print n*3600; else if (s ~ /m$/) print n*60;
                         else if (s ~ /s$/) print n+0; else print 999999 }'; }

# provider_threshold: how deep each pool may be consumed before rotation treats
# it as full. Generous limits ride higher; codex's low shared limit cuts off
# earlier. Kiro has overage disabled — 100% is a hard stop for the rest of the
# month — so leave a margin for the agents already mid-turn when it trips.
provider_threshold() {
  case "$1" in
    openai)    echo "${HIVE_ROTATE_OPENAI_THRESHOLD:-85}" ;;
    anthropic) echo "${HIVE_ROTATE_CLAUDE_THRESHOLD:-90}" ;;
    google)    echo "${HIVE_ROTATE_AGY_THRESHOLD:-90}" ;;
    kiro)      echo "${HIVE_ROTATE_KIRO_THRESHOLD:-95}" ;;
    *)         echo "${HIVE_ROTATE_THRESHOLD:-85}" ;;
  esac
}

# provider_exhausted: is there POSITIVE evidence this provider is out of room?
# Only a real reading at/above its threshold counts. An unknown reading is not
# evidence of anything.
provider_exhausted() {
  local pct="${PCT[$1]:--1}"
  [ "$pct" = "-1" ] && return 1
  [ "$pct" -ge "$(provider_threshold "$1")" ] && return 0
  return 1
}

# provider_recovered is deliberately stricter than !provider_exhausted: a
# failed probe is UNKNOWN, not proof that a previously exhausted account has
# funds again. Treating unknown as recovery caused stranded DeepSeek agents to
# flap between resume and pause every timer tick.
provider_recovered() {
  local pct="${PCT[$1]:--1}"
  [ "$pct" != "-1" ] && [ "$pct" -lt "$(provider_threshold "$1")" ]
}

# provider_ok: may an agent be moved ONTO this provider?
#
# The unknown case needs care, because the probes read a provider THROUGH an
# agent already running on it. Treating every unknown as unusable created a trap
# that emptied the fleet onto one provider overnight:
#
#   probe returns unknown (agent mid-restart) -> provider deemed unusable
#   -> its last agent is evicted -> now NO agent is on it -> probe reports
#   "no-agent" forever -> the provider can never be re-entered.
#
# So "no-agent" (nothing to measure through, no evidence against) permits
# arrival — otherwise the ladder has no way back in. A failed measurement while
# an agent IS present is different: something is wrong there, so do not pile on.
provider_ok() {
  local p="$1" agent="${2:-}" allow_subscription="${3:-0}" pct="${PCT[$1]:--1}" note="${NOTE[$1]:-}"
  provider_login_blocked "$p" && return 1
  provider_exhausted "$p" && return 1
  if [ "$pct" = "-1" ]; then
    case "$note" in
      # Unmeasured, but no evidence against: allow entry. "no-agent" means
      # nothing is running there to read through (google/agy needs a placed,
      # authenticated agent to probe via — see probe_google). "no-usage-api" is
      # kept as a defensive fallback in case a future CLI genuinely has none;
      # agy itself does (`agy --print "/usage"`), confirmed 2026-08-18.
      *no-agent*|*no-usage-api*) : ;;
      *) return 1 ;;   # measurement FAILED, or the binary is missing — stay off
    esac
  fi
  if [ -n "$agent" ]; then
    local c; c=$(cadence_s "$agent")
    # High-volume guard is now codex-ONLY: agy is free and claude's cap is
    # generous, so a 5m driver may use them (bounded by their exhaustion
    # thresholds). codex's low limit is shared with the operator's own CLI —
    # protect it unless the agent's current provider is positively exhausted
    # (the escape hatch choose_rung passes down as allow_subscription).
    if [ "$p" = openai ] && [ "${c:-999999}" -le "$HIGH_VOLUME_CADENCE_S" ] && [ "$allow_subscription" != 1 ]; then
      return 1
    fi
    # agy 5h-window stewardship: a high-cadence agent on the free pool burns
    # the rolling five-hour limit in ~an hour. Cap concurrent placements.
    if [ "$p" = google ] && [ "${c:-999999}" -le "$HIGH_VOLUME_CADENCE_S" ] &&
       [ "${AGY_HV_PLACED:-0}" -ge "$AGY_MAX_HIGH_VOLUME" ]; then
      return 1
    fi
  fi
  return 0
}

# Pick the best rung in an agent's tier whose provider is usable.
#
# Peak pricing is a SOFT preference, not an outage: during a peak window the
# affected providers sink to the bottom of the preference order but stay
# eligible, so a high-volume agent with nowhere else to go keeps working at the
# higher rate instead of stalling or torching a subscription.
# Live count of agents this run has already placed on each provider, so a
# fan-out spreads instead of stampeding onto whichever pool is momentarily
# least-used. Without it every agent independently picks the same "best"
# provider and recreates the single point of failure rotation exists to avoid.
declare -A ASSIGNED
AGY_HV_PLACED=0

# note_placement: record that <agent> was placed on <provider> this run, for
# the fan-out spread and the agy 5h-window cap. Mirrors ASSIGNED accounting.
note_placement() {
  local p="$1" a="$2" c
  ASSIGNED[$p]=$(( ${ASSIGNED[$p]:-0} + 1 ))
  [ "$p" = google ] || return 0
  c=$(cadence_s "$a")
  [ "${c:-999999}" -le "$HIGH_VOLUME_CADENCE_S" ] && AGY_HV_PLACED=$(( ${AGY_HV_PLACED:-0} + 1 ))
}

# rung_in_tier: is the agent's CURRENT backend+model a legitimate rung of its
# tier? Used by the stickiness check below.
rung_in_tier() {
  local tier="$1" b="$2" m="$3"
  tier_members "$tier" | awk -F'|' -v b="$b" -v m="$m" '$3==b && $4==m {found=1} END{exit !found}'
}

# Among eligible rungs, rank by:
#   1. provider COST rank — free (agy) first, then Kiro's roomy monthly
#      credits, then the shared Claude subscription, then protected codex.
#   2. peak — a peak-priced window demotes a provider WITHIN its cost rank, so
#      peak never pushes work from free/cheap onto a dearer pool just to dodge
#      a 2x charge on the last-ranked one.
#   3. load — percent used, plus a penalty per agent already placed here in this
#      run, which is what actually spreads the fan-out.
choose_rung() {
  local tier="$1" agent="${2:-}" p b m allow_subscription=0
  if [ -n "$agent" ] && [ "$METERED_EXHAUSTION_FAILOVER" = 1 ]; then
    local curb curm curp
    curb=$(agent_field "$agent" cli); curm=$(agent_field "$agent" govModel)
    curp=$(provider_of "$curb" "$curm")
    # Waive the subscription guard when the agent's CURRENT provider is
    # POSITIVELY measured exhausted — metered OR subscription. The original
    # metered-only check stranded an agent the moment its subscription
    # (codex) died: no metered fallback existed and every subscription
    # target was still barred, so the only terminal action was pause. An
    # exhausted pool has no cap left to protect; availability wins.
    if provider_exhausted "$curp"; then
      allow_subscription=1
    fi
  fi
  while IFS='|' read -r _ p b m; do
    [ -z "$p" ] && continue
    provider_ok "$p" "$agent" "$allow_subscription" || continue
    local rankbit=0 peakbit=0 rankpct="${PCT[$p]:-99}"
    # A no-agent target is eligible (to avoid a permanent probe deadlock),
    # but unknown headroom must rank AFTER a positively measured target.
    [ "$rankpct" = "-1" ] && rankpct=99
    rankbit=$(provider_cost_rank "$p")
    [ "${PEAK_NOW:-0}" = 1 ] && [[ " $PEAK_PROVIDERS " == *" $p "* ]] && peakbit=1
    printf '%d %d %03d %s|%s|%s\n' "$rankbit" "$peakbit" \
      $(( rankpct + ${ASSIGNED[$p]:-0} * 5 )) "$p" "$b" "$m"
  done <<< "$(tier_members "$tier")" | sort -k1,1n -k2,2n -k3,3n | head -1 | awk '{print $4}'
}

# Kiro overage: with it ENABLED, credits past the monthly limit are billed.
# The threshold keeps agents off before that, but say it out loud.
kiro_overage_warning() {
  case "${NOTE[kiro]:-}" in *overage=ENABLED*)
    echo "WARN: Kiro overage is ENABLED — credits past the monthly limit are billed" ;; esac
  return 0
}

# ── Actions ─────────────────────────────────────────────────────────────
# gather must run before any action that reads probes.
gather

# ── Contributor workers ────────────────────────────────────────────────
# The k8s contributor Deployments (talos-k8s/hive-contributors) each pin ONE
# backend via AGENT_BACKEND, and nothing was reconciling them against provider
# headroom. A worker whose provider is exhausted does not fail quietly: it
# accepts a task from the hub, cannot run it, and hands it back — burning a hub
# slot and the task's retry budget on every cycle.
#
# Same probe, same thresholds, same decision engine as the agents above — the
# only difference is the lever. There is no per-worker model to move, so the
# action is replica count: park at 0 while the provider is dry, restore to 1
# the moment it is positively measured healthy again. Scaling to 0 keeps the
# PVC, the credentials and the contributor identity intact, so coming back is
# just a scale-up, not a re-registration.
CONTRIB_NS="${HIVE_CONTRIB_NS:-hive-contributors}"

# deployment -> the provider its pinned backend actually resolves to. Read from
# the live Deployment rather than hardcoded, because the mapping is not obvious:
# pi-codex-contributor runs AGENT_BACKEND=pi with AGENT_MODEL=openai-codex/...,
# so it consumes OPENAI quota, not deepseek. provider_of must see BOTH fields
# or a `pi` shell is misread as deepseek and parked against the wrong pool.
# All fields come from ONE list call (DEPLOYS), not three kubectl calls per
# deployment.
contrib_field() {  # <deployment> <jq expr on the deployment>
  printf '%s' "$DEPLOYS" | jq -r --arg d "$1" ".items[] | select(.metadata.name==\$d) | $2 // empty" 2>/dev/null
}
contrib_provider() {
  local d="$1" b m
  b=$(contrib_field "$d" '(.spec.template.spec.containers[0].env // [] | map(select(.name=="AGENT_BACKEND"))[0].value)')
  m=$(contrib_field "$d" '(.spec.template.spec.containers[0].env // [] | map(select(.name=="AGENT_MODEL"))[0].value)')
  [ -z "$b" ] && { echo unknown; return; }
  provider_of "$b" "$m"
}

reconcile_contributors() {
  local ds d p want have
  # The contributor pool is FLEET-WIDE, not per-hive: one set of deployments
  # serves every spoke. Only the run managing the primary hive may scale them —
  # otherwise two spokes' runs race, each scaling on its own view of provider
  # headroom, and a contributor flaps between 0 and 1 every tick.
  if [ "$NS" != "${HIVE_PRIMARY_NS:-hive}" ]; then
    echo "contributors: skipped — pool is managed by the primary hive (${HIVE_PRIMARY_NS:-hive}), not $NS"
    return 0
  fi
  DEPLOYS=$(k8s_get "/apis/apps/v1/namespaces/$CONTRIB_NS/deployments")
  ds=$(printf '%s' "$DEPLOYS" | jq -r '.items[]?.metadata.name' 2>/dev/null)
  [ -z "$ds" ] && { echo "no contributor deployments in $CONTRIB_NS"; return 0; }
  for d in $ds; do
    p=$(contrib_provider "$d")
    have=$(contrib_field "$d" '.spec.replicas')
    have=${have:-0}
    if provider_exhausted "$p"; then
      want=0
    elif provider_recovered "$p"; then
      want=1
    elif [ "$have" = 0 ]; then
      # Unmeasured AND already parked is a DEADLOCK, not a steady state: several
      # providers can only be read through a live consumer, so parking the last
      # one makes the provider permanently unmeasurable and "leave it alone"
      # keeps it at zero forever. Observed 2026-09-02: the entire contributor
      # fleet sat at 0 replicas while its providers were merely unreadable.
      # Restore ONE worker to make the provider measurable again — the same
      # "no-agent permits arrival" rule the agent path already uses.
      want=1
      printf '%-24s %-9s unmeasurable while parked -> restoring 1 to re-probe\n' "$d" "$p"
    else
      # Unmeasured but still running: leave it. Scaling down on a failed
      # measurement would park a worker that may be perfectly fine.
      printf '%-24s %-9s %s (unmeasured — left at %s)\n' "$d" "$p" "${NOTE[$p]:-}" "$have"
      continue
    fi
    if [ "$have" = "$want" ]; then
      printf '%-24s %-9s ok (replicas=%s)\n' "$d" "$p" "$have"
      continue
    fi
    if [ "$want" = 0 ]; then
      printf '%-24s %-9s EXHAUSTED -> parking (replicas %s->0)\n' "$d" "$p" "$have"
    else
      printf '%-24s %-9s recovered -> restoring (replicas %s->1)\n' "$d" "$p" "$have"
    fi
    [ "$ACTION" = plan ] && continue
    k8s_scale "$CONTRIB_NS" "$d" "$want" \
      || printf '    ! scale failed for %s\n' "$d"
  done
}

if [ "$ACTION" = contributors ]; then
  printf '%-24s %-9s %s\n' DEPLOYMENT PROVIDER STATE
  reconcile_contributors
  exit 0
fi

# pane_classify <agent>: ready|auth|shell|empty — the watchdog's liveness
# probe, a k8s-livenessProbe analog. The dashboard's `state=running` is a
# config echo, not an observation; the pane is the truth (see RFC #4665).
pane_classify() {
  # v5 publishes each agent's last pane capture as `liveSummary` in
  # /api/status, so classification needs NO tmux exec (previously 2-3 execs per
  # agent per pass, x13 agents, every 5 minutes). Patterns live in hive-lib.sh
  # (pane_classify_text) and are unit-tested against real captured panes.
  agent_field "$1" liveSummary | pane_classify_text
}

# choose_rung_healthy <tier> <agent>: like choose_rung but ONLY rungs whose
# provider is positively MEASURED healthy (known pct below its threshold),
# never the agent's current provider. Used by the watchdog to rotate OFF a
# backend that is failing liveness (auth-broken / crash-looping), where
# restarting on the same rung just re-breaks it — the "unhealthy backend"
# escape hatch the user asked for (RFC #4665).
choose_rung_healthy() {
  local tier="$1" agent="$2" curp p b m
  curp=$(provider_of "$(agent_field "$agent" cli)" "$(agent_field "$agent" govModel)")
  while IFS='|' read -r _ p b m; do
    [ -z "$p" ] && continue
    [ "$p" = "$curp" ] && continue
    provider_ok "$p" "$agent" 1 || continue     # allow subscription escape
    [ "${PCT[$p]:--1}" = "-1" ] && continue     # must be MEASURED
    provider_exhausted "$p" && continue          # and not exhausted
    printf '%d %03d %s|%s|%s\n' "$(provider_cost_rank "$p")" "${PCT[$p]}" "$p" "$b" "$m"
  done <<< "$(tier_members "$tier")" | sort -k1,1n -k2,2n | head -1 | awk '{print $3}'
}

if [ "$ACTION" = watchdog ]; then
  # 1) Shared-state hygiene, ONE exec. Agents share $HOME subtrees and the CLIs
  # rewrite their state files mode 600 owned by whichever agent wrote last, so
  # the next agent hits EACCES and lands in a first-run wizard:
  #   - agy: ~/.gemini/antigravity-cli onboarding/settings (theme/ToS picker)
  #   - codex: /data/home/.codex-<agent> sqlite ("attempt to write a readonly
  #     database"), because rotation moves agents across backends
  #   - muse (v5): ~/.config/muse/trust.json — every agent's ~/.config is a
  #     symlink to the shared /data/home/.config, and one agent's 600 trust
  #     store parks the others on "Do you trust this workspace? ... Permission
  #     denied (os error 13)" (reef/outreach, 2026-09-24).
  # Directories 2770 (setgid keeps the `node` group), files 660.
  # Runs when a wizard is seen, and otherwise at most hourly: it is an exec,
  # and v5's own entrypoint already repairs ~/.gemini ("perm guard").
  gemini_hygiene() {
    dry && return 0
    echo "$now_s" > "$STATE_DIR/hygiene-last" 2>/dev/null
    # agy: only the top-level settings/onboarding json and cache/ — the
    # files whose mode-600 rewrite causes the wizard. A recursive sweep of
    # antigravity-cli (thousands of logs/conversations) blew the exec's 90 s
    # timeout on the loaded node, and v5's entrypoint "perm guard" already
    # maintains the rest of ~/.gemini.
    timeout 90 kubectl exec -n "$NS" "$POD" -- sh -c '
      g=/data/home/.gemini/antigravity-cli
      if [ -d "$g" ]; then
        chown dev:node "$g" "$g"/*.json "$g/cache" "$g"/cache/* 2>/dev/null
        chmod 660 "$g"/*.json "$g"/cache/* 2>/dev/null
        chmod 2770 "$g" "$g/cache" 2>/dev/null
      fi
      for d in /data/home/.config/muse /data/home/.codex-*; do
        [ -d "$d" ] || continue
        chown -R dev:node "$d" 2>/dev/null
        find "$d" -type f ! -perm -660 -exec chmod 660 {} + 2>/dev/null
        find "$d" -type d ! -perm -2770 -exec chmod 2770 {} + 2>/dev/null
      done' >/dev/null 2>&1
  }
  # heal_restart <agent>: POST /api/restart; for agy/muse agents, from INSIDE
  # the pod in the same exec that first reopens the shared first-run state.
  #
  # Why (2026-09-24): every agy launch rewrites the SHARED
  # ~/.gemini/antigravity-cli/cache/onboarding.json mode 0600 under its own
  # uid, so the NEXT agy agent to launch gets EACCES ("failed to load
  # onboarding status ... permission denied") and sits on the theme wizard.
  # v5's entrypoint perm guard does not cover that file and runs as `dev`,
  # which cannot chmod a file an agent uid owns; only a root exec can. Doing
  # the repair and the restart in one exec guarantees the relaunching CLI
  # reads a group-readable file. muse's trust.json has the same shape.
  heal_restart() {
    local a="$1" cli; cli=$(agent_field "$a" cli)
    case "$cli" in
      agy|muse)
        # shellcheck disable=SC2016
        timeout 200 kubectl exec -n "$NS" "$POD" -- sh -c '
          for f in /data/home/.gemini/antigravity-cli/cache/*.json /data/home/.gemini/antigravity-cli/*.json \
                   /data/home/.config/muse/*.json; do
            [ -f "$f" ] || continue
            chown dev:node "$f" 2>/dev/null; chmod 660 "$f" 2>/dev/null
          done
          curl -sS -X POST --max-time 150 -H "Cookie: hive_session=$2" "http://127.0.0.1:3002/api/restart/$1"' \
          sh "$a" "$SID" 2>/dev/null \
          || hive_api POST "/api/restart/$a"
        ;;
      *) hive_api POST "/api/restart/$a" ;;
    esac
  }

  now_s=$(date +%s)
  hl=$(cat "$STATE_DIR/hygiene-last" 2>/dev/null || echo 0)
  [ $(( now_s - ${hl:-0} )) -ge 3600 ] && gemini_hygiene

  # 1b) RENEWAL WAKE-UP. gather() records when an exhausted provider comes
  # back. Once that moment passes, re-derive placement from scratch (apply
  # re-probes, re-places, un-strands, reconciles contributors).
  renewed=""
  now_s=$(date +%s)
  for f in "$STATE_DIR"/resets.d/*; do
    [ -e "$f" ] || continue
    due=$(cat "$f" 2>/dev/null)
    [ -n "$due" ] && [ "$now_s" -ge "$due" ] 2>/dev/null || continue
    renewed="$renewed $(basename "$f")"
    dry || rm -f "$f"
  done
  if [ -n "$renewed" ]; then
    printf 'renewal reached for:%s — re-deciding placement from current credits\n' "$renewed"
    dry || { HIVE_USAGE_MAX_AGE_S=0 "$0" apply || echo "  ! re-decision failed" >&2; }
    exit 0
  fi

  # 2) Per-agent liveness. Heal = POST /api/restart, which in v5 kills and
  # relaunches the CLI session. The old C-c + kick sequence typed into panes
  # (dangerous on a login MENU: the kick's Enter selected "Claude account with
  # subscription" and advanced into a device flow no one would ever finish),
  # and v5's kick is async and refuses a dead session anyway.
  #
  # BACKOFF is exponential per agent (5, 10, 20 ... 120 min; see
  # watchdog_backoff_s) and resets the first time the agent is seen ready. A
  # fixed 5-minute interval restarted permanently-broken agents ~288x/day, and
  # v5 counts every one into its crash-loop breaker (`BLOCKED: crash-looping`).
  #
  # MUTATION BUDGET. Every heal, repair and effort set restarts an agent
  # INSIDE the API request (v5), 30-60 s each on the loaded node. A pass
  # with three effort fixes took 249 s of its 280 s deadline, so each pass
  # does at most HIVE_WATCHDOG_MAX_MUTATIONS of them and starts none after
  # HIVE_WATCHDOG_BUDGET_S; the rest wait for the next 5-minute pass.
  healed=0; human=""; mutations=0
  # v5's /api/status is a periodically rebuilt snapshot that can lag minutes
  # (observed 2-12 min under load). A frozen snapshot would read as a frozen
  # pane, so stall judgement is skipped when the snapshot itself is old.
  snap_age=$(( now_s - $(printf '%s' "$STATUS_JSON" | jq -r '.timestamp // empty | fromdateiso8601? // 0' 2>/dev/null || echo 0) ))
  stall_ok=1
  if [ "$snap_age" -gt "${HIVE_WATCHDOG_MAX_SNAPSHOT_AGE_S:-900}" ]; then
    stall_ok=0
    echo "status snapshot is ${snap_age}s old — stall detection skipped this pass"
  fi
  budget_ok() {
    [ "$mutations" -lt "${HIVE_WATCHDOG_MAX_MUTATIONS:-3}" ] &&
    [ $(( $(date +%s) - RUN_START )) -lt "${HIVE_WATCHDOG_BUDGET_S:-170}" ]
  }
  for a in $(agent_names); do
    [ "$(agent_field "$a" paused)" = true ] && continue
    if budget_ok && repair_mismatch "$a"; then healed=$((healed+1)); mutations=$((mutations+1)); continue; fi
    # agy effort drift (a model set by hand/pace/older rotate without effort).
    if [ -n "$(effort_change "$(agent_field "$a" cli)" "$(agent_field "$a" govModel)" "$(effort_recorded "$a")")" ]; then
      if budget_ok; then
        sync_effort "$a" "$(agent_field "$a" cli)" "$(agent_field "$a" govModel)"; mutations=$((mutations+1))
      else
        printf '%-14s effort fix deferred to the next pass (budget)\n' "$a"
      fi
    fi
    lk="$STATE_DIR/watchdog-last-kick-$a"
    pane=$(agent_field "$a" liveSummary)
    state=$(printf '%s' "$pane" | pane_classify_text)
    # CONFIRM ON THE LIVE PANE before judging. /api/status is a snapshot that
    # lagged 9+ minutes on school (2026-09-24): an agent the previous pass had
    # already healed still showed its old wizard there, and would have been
    # restarted again. GET /api/pane is v5's 3-second pane cache. Fetched only
    # for agents that look unhealthy or are mid-turn (stall candidates).
    if [ "$state" != ready ] || [ "$(agent_field "$a" busy)" = working ]; then
      live=$(hive_api GET "/api/pane/$a?lines=60" 30 | jq -r 'if .lines then .lines | join("\n") else empty end' 2>/dev/null)
      if [ -n "$live" ]; then
        pane=$live
        state=$(printf '%s' "$pane" | pane_classify_text)
      fi
    fi
    if [ "$state" = ready ] && [ "$stall_ok" = 1 ] && pane_stalled "$STATE_DIR/watchdog-pane-$a" \
         "$(agent_field "$a" busy)" "$pane" "$now_s"; then
      state=stalled
    fi
    if [ "$state" = ready ]; then
      printf '%-14s liveness ok\n' "$a"
      dry || rm -f "$lk"
      continue
    fi
    # A login only a human can complete. Copilot's device flow is never
    # headlessly recoverable, and v5 flags needsLogin itself. Restarting just
    # burns the crash-loop budget: report it and move on.
    if [ "$(agent_field "$a" cli)" = copilot ] && { [ "$state" = auth ] || [ "$(agent_field "$a" needsLogin)" = true ] ||
         { [ "$(agent_field "$a" authKnown)" = true ] && [ "$(agent_field "$a" authAvailable)" != true ]; }; }; then
      printf '%-14s %-8s NEEDS HUMAN LOGIN (copilot device flow) — not restarting\n' "$a" "$state"
      human="$human $a"
      continue
    fi
    last=0; n=0
    # Pre-2026-09-24 files hold a bare epoch: count that as one prior heal.
    [ -f "$lk" ] && { read -r last n < "$lk"; n=${n:-1}; }
    wait_s=$(watchdog_backoff_s "${n:-0}")
    if [ $(( now_s - ${last:-0} )) -lt "$wait_s" ]; then
      printf '%-14s %-8s (healed %sx, backing off %sm)\n' "$a" "$state" "${n:-0}" $(( wait_s / 60 ))
      continue
    fi
    if ! budget_ok; then
      printf '%-14s %-8s heal deferred to the next pass (budget)\n' "$a" "$state"
      continue
    fi
    mutations=$((mutations+1))
    printf '%-14s %-8s -> healing (restart #%s)\n' "$a" "$state" $(( ${n:-0} + 1 ))
    if [ "$state" = wizard ]; then gemini_hygiene; fi
    # Backend-level failure (auth chrome, or a CLI that dies to a bare shell):
    # restarting on the same rung just re-breaks it — rotate onto a
    # positively-measured-healthy rung first (place_agent restarts it).
    rotated=0
    if [ "$state" = auth ] || [ "$state" = shell ]; then
      if ! pinned "$a"; then
        want=$(choose_rung_healthy "$(tier_of "$a")" "$a")
        if [ -n "$want" ]; then
          IFS='|' read -r _wp wb wm <<< "$want"
          if [ "$wb" != "$(agent_field "$a" cli)" ] || [ "$wm" != "$(agent_field "$a" govModel)" ]; then
            printf '%-14s %-8s rotating off -> %s %s\n' "$a" "$state" "$wb" "$wm"
            dry || { place_agent "$a" "$wb" "$wm" && rotated=1; }
          fi
        fi
      fi
    fi
    if [ "$rotated" = 0 ] && ! dry; then
      rs=$(heal_restart "$a" | jq -r '.status // .error' 2>/dev/null)
      printf '%-14s %-8s restarted (%s)\n' "$a" "$state" "$rs"
      rm -f "$STATE_DIR/watchdog-pane-$a"
    fi
    dry || echo "$now_s $(( ${n:-0} + 1 ))" > "$lk"
    healed=$((healed+1))
  done
  echo "watchdog: $healed agent(s) healed"
  [ -n "$human" ] && echo "watchdog: needs a human login:$human"
  exit 0
fi


if [ "$ACTION" = probe ]; then
  printf '%-11s %-9s %s\n' PROVIDER USED NOTE
  for p in $PROVIDERS; do
    v="${PCT[$p]}"; [ "$v" = "-1" ] && v="unknown" || v="${v}%"
    printf '%-11s %-9s %s\n' "$p" "$v" "${NOTE[$p]}"
  done
  in_peak_window && echo && echo "peak window ACTIVE (UTC $(date -u +%H:%M)); avoiding: $PEAK_PROVIDERS"
  kiro_overage_warning
  exit 0
fi

if [ "$ACTION" = restore ]; then
  # Undo path for an unattended timer: walk the rotation journal newest-first and
  # put each agent back on the rung it held BEFORE this tool first moved it.
  # Newest-first + a seen-set means an agent rotated several times returns to its
  # original placement, not to an intermediate hop.
  [ -s "$STATE_DIR/rotated" ] || { echo "nothing to restore (no journal at $STATE_DIR/rotated)"; exit 0; }
  declare -A SEEN; n=0
  while IFS='|' read -r a p b m; do
    [ -z "$a" ] && continue
    [ -n "${SEEN[$a]:-}" ] && continue
    SEEN[$a]=1
    curb=$(agent_field "$a" cli); curm=$(agent_field "$a" govModel)
    if [ "$curb" = "$b" ] && [ "$curm" = "$m" ]; then
      printf '%-14s already on %s %s\n' "$a" "$b" "$m"; continue
    fi
    sw=$(hive_api POST "/api/switch/$a/$b" | jq -r '.status // .error')
    if [ "$sw" != switched ]; then printf '%-14s ! switch failed: %s\n' "$a" "$sw"; continue; fi
    md=$(hive_api POST "/api/model/$a/$(hive_model_path "$m")" | jq -r '.status // .error')
    printf '%-14s restored -> %s %s (%s)\n' "$a" "$b" "$m" "$md"
    n=$((n+1))
  done <<< "$(tac "$STATE_DIR/rotated")"
  mv "$STATE_DIR/rotated" "$STATE_DIR/rotated.$(date +%s).done"
  echo "restored $n agent(s); journal archived"
  exit 0
fi

# Un-strand: an agent parked because its metered provider ran dry must come back
# by itself once the account is topped up, or a paused driver silently becomes a
# permanent one and the fleet never recovers without a human.
if [ -s "$STATE_DIR/stranded" ]; then
  keep=""
  while IFS='|' read -r sa sp sb sm; do
    [ -z "$sa" ] && continue
    if ! provider_recovered "$sp"; then
      # Keep the safety pause on a failed/unknown reading; only a successful
      # below-threshold probe proves funds or quota actually recovered.
      keep="$keep$sa|$sp|$sb|$sm"$'\n'
      continue
    fi
    printf '%-14s %-9s recovered -> resuming\n' "$sa" "$sp"
    [ "$ACTION" = plan ] && { keep="$keep$sa|$sp|$sb|$sm"$'\n'; continue; }
    hive_api POST "/api/resume/$sa" >/dev/null
  done < "$STATE_DIR/stranded"
  printf '%s' "$keep" > "$STATE_DIR/stranded"
fi

# SAFETY NET: resume any agent that is paused while the provider it is sitting
# on is positively measured HEALTHY.
#
# The journal above is the normal recovery path, but it is a local file and the
# pause lives in the cluster — so the two can desynchronise, and when they do
# the agent is parked forever with nothing left that knows to free it. Ways
# that happened here: the journal was truncated during an incident; the pause
# was applied by a different host or by hand; the pod was rebuilt. The result
# is identical and silent — a full fleet idle while every provider is healthy,
# which is exactly the "agents die and never come back" failure this exists to
# prevent.
#
# Deliberately conservative, because it cannot tell an operator's pause from a
# rotation's:
#   - requires a POSITIVE below-threshold reading (never an unknown probe),
#   - requires the agent's current rung to be a legitimate member of its tier,
#     so a half-placed or mismatched agent is left alone for the repair path,
#   - skips login-detector pauses, which mean the BACKEND is broken and would
#     just re-pause on resume.
# Set HIVE_ROTATE_AUTORESUME=0 to hold paused agents down (e.g. while
# deliberately keeping the fleet quiet).
# ── OPERATOR PAUSES ARE NOT STATE, THEY ARE CODE ────────────────────────
#
# POLICY (2026-09-06): keeping the hives unpaused and functional is the whole
# job of hive-ops. A pause applied by hand through the dashboard is therefore
# NOT durable fleet state — it is an undeclared local edit, and it is exactly
# how a spoke ends up silently idle. Observed the same day: 11 school agents sat
# on `manual pause` for ~19 hours, invisible to every dashboard that only shows
# "running", while the governor burned eval cycles computing them as due and
# then skipping them.
#
# So a `dashboard-api` pause is resumed on the next pass, unconditionally —
# NOT gated on provider health or rung membership the way the recovery net
# below is, because an operator pause is not evidence of provider trouble and
# waiting for a positive probe is what let these persist. If the provider really
# is dry, placement further down re-strands the agent with a reason that names
# the provider, which is a far better record than "manual pause".
#
# TO KEEP AN AGENT PAUSED, COMMIT IT. HIVE_ROTATE_HOLD is a comma-separated
# allowlist set per-spoke in talos-k8s/hive-ops/hive-ops.yaml — that manifest is
# in git, so a deliberate hold is reviewable, greppable, and survives a pod
# rebuild. Anything not in it gets resumed. There is deliberately no way to
# express a durable pause outside of code.
#
# on-demand agents (pausedTrigger=startup, onDemand=true) are NOT operator
# pauses — they are paused by design until an inception triggers them, and are
# skipped here.
# Agents whose PLACEMENT is fixed by the operator. Comma-separated, declared in
# talos-k8s/hive-ops/hive-ops.yaml so a pin is reviewable in git for the same
# reason HIVE_ROTATE_HOLD is.
#
# The hive config has a `cli_pinned` field, but THIS script never read it, so a
# model set by hand through the dashboard was silently reverted at the next
# rotation. Pinning has to be honoured by whatever does the placing.
#
# A pinned agent is still probed, still healed by the watchdog, and still
# un-stranded — only the rung choice is left alone.
# (PIN/pinned live near the top so the watchdog can see them.)

HOLD=",$(printf '%s' "${HIVE_ROTATE_HOLD:-}" | tr -d '[:space:]'),"
held() { [ "$HOLD" != ",," ] && [ "${HOLD#*,$1,}" != "$HOLD" ]; }
# Agents hive-peak.sh paused for a DeepSeek peak window are a declared,
# scheduled pause (peak-resume restores them), not an operator's stray one.
# Without this the auto-resume below undid every peak pause on the next tick.
PEAK_PAUSED_FILE="${HIVE_PEAK_STATE:-$(dirname "$STATE_DIR")/hive-rotate/peak-paused}"
peak_held() {
  [ "$NS" = "${HIVE_PRIMARY_NS:-hive}" ] && [ -s "$PEAK_PAUSED_FILE" ] && grep -qx "$1" "$PEAK_PAUSED_FILE"
}

if [ "${HIVE_ROTATE_AUTORESUME:-1}" = 1 ]; then
  for a in $(agent_names); do
    [ "$(agent_field "$a" paused)" = true ] || continue
    [ "$(agent_field "$a" onDemand)" = true ] && continue
    # Is this row one of OURS? The journal records the provider as it was at
    # strand time and placement moves afterwards, so a row can name a provider
    # the agent is no longer on. Observed 2026-09-06:
    # `operations|anthropic|codex|claude-sonnet-4-6` while the agent was actually
    # placed on openai/gpt-5.6-luna. The row still means "we parked this", so we
    # do not treat it as an operator pause — but it must NOT short-circuit the
    # recovery net below, which reads the CURRENT rung and is the only thing that
    # can free an agent whose journal row has gone stale.
    ours=0
    if [ -s "$STATE_DIR/stranded" ] && grep -q "^$a|" "$STATE_DIR/stranded" 2>/dev/null; then
      ours=1
    fi

    if [ "$(agent_field "$a" pausedTrigger)" = dashboard-api ] && [ "$ours" = 0 ]; then
      if held "$a"; then
        printf '%-14s %-9s held paused by HIVE_ROTATE_HOLD (declared in git)\n' "$a" "operator"
        continue
      fi
      if peak_held "$a"; then
        printf '%-14s %-9s held paused by the peak window (hive-peak-resume restores it)\n' "$a" "peak"
        continue
      fi
      printf '%-14s %-9s operator pause -> resuming (not declared in HIVE_ROTATE_HOLD)\n' "$a" "operator"
      [ "$ACTION" = plan ] && continue
      rs=$(hive_api POST "/api/resume/$a" | jq -r '.status // .error')
      [ "$rs" = "resumed" ] || printf '    ! resume failed: %s\n' "$rs"
      [ -s "$STATE_DIR/stranded" ] && sed -i "/^$a|/d" "$STATE_DIR/stranded"
      continue
    fi

    [ "$(agent_field "$a" pausedTrigger)" = login-detector ] && continue
    tier=$(tier_of "$a"); [ -z "$tier" ] && continue
    curb=$(agent_field "$a" cli); curm=$(agent_field "$a" govModel)
    curp=$(provider_of "$curb" "$curm")
    provider_recovered "$curp" || continue
    rung_in_tier "$tier" "$curb" "$curm" || continue
    printf '%-14s %-9s paused on a healthy provider -> resuming\n' "$a" "$curp"
    [ "$ACTION" = plan ] && continue
    rs=$(hive_api POST "/api/resume/$a" | jq -r '.status // .error')
    [ "$rs" = "resumed" ] || printf '    ! resume failed: %s\n' "$rs"
    # Drop any stale journal row so the normal path stops waiting on it too.
    [ -s "$STATE_DIR/stranded" ] && sed -i "/^$a|/d" "$STATE_DIR/stranded"
  done
fi

# The pacer's demotion journal. hive-pace runs once for every hive and keeps
# it in the PRIMARY state dir, keyed "<ns>/<agent>".
PACE_DEMOTED="${HIVE_PACE_DEMOTED:-$(dirname "$STATE_DIR")/hive-rotate/pace-demoted}"

changed=0
for a in $(agent_names); do
  if pinned "$a"; then
    printf '%-14s %-9s pinned by HIVE_ROTATE_PIN — placement left alone\n' "$a" "$(provider_of "$(agent_field "$a" cli)" "$(agent_field "$a" govModel)")"
    continue
  fi
  tier=$(tier_of "$a"); [ -z "$tier" ] && continue
  curb=$(agent_field "$a" cli); curm=$(agent_field "$a" govModel)
  curp=$(provider_of "$curb" "$curm")

  # STICKINESS — this is a FAILOVER system, not an optimizer.
  # If the agent's current provider is usable and its current rung is a
  # legitimate member of its tier, leave it alone even when something better
  # ranked exists. Without this the fleet churns every tick chasing whichever
  # pool is momentarily least-used, and deliberately-placed agents (such as a
  # canary proving a failover path still works) get yanked off healthy
  # providers. Rotate because something is EXHAUSTED, not because something
  # else looks marginally nicer.
  # Staying is judged ONLY on positive evidence of exhaustion — never on a
  # failed measurement. Requiring provider_ok() here (which also rejects
  # unknowns) meant a single unreadable probe evicted a perfectly healthy agent,
  # and because the probe reads through an agent on that provider, evicting the
  # last one made the provider permanently unmeasurable and therefore
  # permanently unusable. The fleet drained onto one provider overnight that
  # way. Not being able to measure is not a reason to move anyone.
  #
  # A rung the PACER demoted this agent onto (opus -> sonnet, -high -> -low)
  # counts as in-tier. Without this the two controllers fought every tick:
  # pace demoted a T1 agent to sonnet, rotate saw sonnet as off-tier and put it
  # back, pace demoted it again — ~25 round trips for reef sec-check/strategist
  # in pace-demoted, each one an agent restart that v5 then scored as
  # crash-looping. Pace owns the rung WITHIN a provider; rotate owns the
  # provider.
  demoted_from=$(pace_demoted_from "$PACE_DEMOTED" "$NS" "$a" "$curm")
  if ! provider_exhausted "$curp" && ! provider_login_blocked "$curp" &&
     { rung_in_tier "$tier" "$curb" "$curm" ||
       { [ -n "$demoted_from" ] && rung_in_tier "$tier" "${demoted_from%%|*}" "${demoted_from#*|}"; }; }; then
    note_placement "$curp" "$a"
    printf '%-14s %-9s %s ok%s\n' "$a" "$curp" "$curm" "${demoted_from:+ (pace-demoted from ${demoted_from#*|})}"
    continue
  fi

  want=$(choose_rung "$tier" "$a")
  if [ -z "$want" ]; then
    # Stranded: this agent's current provider is exhausted and no rung in its
    # tier will take it. For high-cadence agents that is the normal outcome of
    # the metered-only rule above — a 5m-cadence agent is barred from the
    # subscription pools precisely so it cannot drain a weekly cap in an
    # afternoon and take the operator's own CLI down with it.
    #
    # Leaving it running is the worst of the three options: the governor keeps
    # kicking it into a backend that cannot serve, so it fails silently and
    # looks healthy. Pausing is honest degradation — the fleet's low-cadence
    # agents keep working on the other providers, and a paused driver is a loud
    # signal to top the metered account back up.
    if provider_exhausted "$curp"; then
      printf '%-14s %-9s STRANDED (no rung at %s) -> pausing\n' "$a" "$curp" "$tier"
      changed=$((changed+1))
      [ "$ACTION" = plan ] && continue
      if [ "$(agent_field "$a" paused)" != "true" ]; then
        st=$(hive_api POST "/api/pause/$a" | jq -r '.status // .error')
        printf '    paused: %s\n' "$st"
        printf '%s|%s|%s|%s\n' "$a" "$curp" "$curb" "$curm" >> "$STATE_DIR/stranded"
      fi
    else
      printf '%-14s %-9s %s ok (no better rung available)\n' "$a" "$curp" "$curm"
    fi
    continue
  fi
  IFS='|' read -r wp wb wm <<< "$want"
  note_placement "$wp" "$a"
  if [ "$wb" = "$curb" ] && [ "$wm" = "$curm" ]; then
    printf '%-14s %-9s %s ok\n' "$a" "$curp" "$curm"
    continue
  fi
  printf '%-14s %-9s %s  ->  %-9s %s\n' "$a" "$curp" "$curm" "$wp" "$wm"
  changed=$((changed+1))
  [ "$ACTION" = plan ] && continue

  # switch -> model -> effort, with rollback (see place_agent).
  place_agent "$a" "$wb" "$wm" || continue
  md=model_set
  # login-detector pauses are provider failures, not operator pauses. Release
  # this safety pause only after both fallback mutations succeeded.
  if [ "$(agent_field "$a" paused)" = true ] &&
     [ "$(agent_field "$a" pausedTrigger)" = login-detector ] &&
     [ "$md" = "model_set" ]; then
    rs=$(hive_api POST "/api/resume/$a" | jq -r '.status // .error')
    [ "$rs" = "resumed" ] || echo "    ! resume failed: $rs"
  fi
  # An agent WE stranded is now on a healthy provider: the move to a better
  # rung IS the recovery. Clear the stranded marker (so the un-strand block
  # stops waiting on the old provider) and bring the agent back up. Without
  # this, a failover off a dead subscription stayed paused forever.
  if [ -s "$STATE_DIR/stranded" ] && grep -q "^$a|" "$STATE_DIR/stranded"; then
    sed -i "/^$a|/d" "$STATE_DIR/stranded"
    if [ "$(agent_field "$a" paused)" = true ]; then
      rs=$(hive_api POST "/api/resume/$a" | jq -r '.status // .error')
      [ "$rs" = "resumed" ] || echo "    ! resume failed: $rs"
      printf '%-14s resumed on %s (was stranded on %s)\n' "$a" "$wp" "$curp"
    fi
  fi
  printf '%s|%s|%s|%s\n' "$a" "$curp" "$curb" "$curm" >> "$STATE_DIR/rotated"
  # A pool we just left BECAUSE it filled up: don't re-place a canary on it for
  # a long while (write an epoch expiry — a plain `touch` produced an EMPTY
  # file that the -s cooldown test never saw, so the canary re-parked on the
  # dead pool every ~40 min until the reset).
  if provider_exhausted "$curp"; then
    echo $(( $(date +%s) + CANARY_EXHAUSTED_COOLDOWN_MIN * 60 )) > "$STATE_DIR/canary-cool-$curp" 2>/dev/null
  fi
done

# ── Observability canaries ─────────────────────────────────────────────
# codex/claude usage is readable ONLY through a live pane on that provider
# (the probes type /status and /usage into the TUI; neither CLI exposes quota
# headlessly — verified 2026-08-23). When the last agent is rotated off a
# subscription pool it becomes unmeasurable ("no-agent") and the fleet flies
# blind. Park ONE low-cadence agent on each subscription pool that is not
# positively exhausted, so the probe always has a pane. A cooldown file stops
# a pool that just evicted its canary (because it filled up) from re-spawning
# one immediately.
# CANARY_EXHAUSTED_COOLDOWN_MIN (120min transient vs. 720min for a positively
# exhausted pool, so a weekly codex reset is picked up within a day) is
# defined earlier, alongside the other rotation tunables — see the comment
# there for why.

# canary_cooled: 0 (true) while <provider> is cooling down. The cooldown file
# holds an epoch seconds expiry (eviction writes now+cooldown). An empty or
# unparseable file is treated as expired — never permanently block a pool.
canary_cooled() {
  local f="$STATE_DIR/canary-cool-$1" exp
  [ -f "$f" ] || return 1
  exp=$(cat "$f" 2>/dev/null)
  [ -n "$exp" ] && [ "$exp" -gt "$(date +%s)" ] 2>/dev/null && return 0
  return 1
}
canary_eligible() {  # provider -> LONGEST-cadence agent whose tier has a rung there
  # The canary exists only so the probe has a pane; it must cost almost
  # nothing, so prefer the RAREST kicker. For the protected pool (openai) skip
  # high-volume agents outright — parking a 5m driver on codex would burn the
  # very cap the guard exists to protect.
  local p="$1" best_a="" best_c=-1 a tier c
  for a in $(agent_names); do
    [ "$(agent_field "$a" paused)" = true ] && continue
    tier=$(tier_of "$a"); [ -z "$tier" ] && continue
    tier_members "$tier" | awk -F'|' -v p="$p" '$2==p{found=1} END{exit !found}' || continue
    c=$(cadence_s "$a")
    if [ "$p" = openai ] && [ "${c:-999999}" -le "$HIGH_VOLUME_CADENCE_S" ]; then
      continue   # high-volume agent must not canary the protected pool
    fi
    [ "${c:-999999}" -gt "$best_c" ] && { best_c=$c; best_a=$a; }
  done
  [ -n "$best_a" ] && echo "$best_a"
}

if [ "${HIVE_ROTATE_CANARIES:-1}" = 1 ]; then
  # Only codex needs a canary now: claude's probe reads the OAuth usage API
  # directly (agent-independent) and agy's reads the CLI headlessly — but the
  # codex /status screen is readable only through a live pane.
  # shellcheck disable=SC2043  # one pool today; the loop is the extension point
  for p in openai; do
    [ -n "$(first_agent_on "$p")" ] && continue          # probe already has a pane
    provider_exhausted "$p" && continue                   # positively full: useless canary
    canary_cooled "$p" && continue                        # recently evicted from here
    a=$(canary_eligible "$p"); [ -z "$a" ] && continue
    tier=$(tier_of "$a")
    wb=$(tier_members "$tier" | awk -F'|' -v p="$p" '$2==p{print $3; exit}')
    wm=$(tier_members "$tier" | awk -F'|' -v p="$p" '$2==p{print $4; exit}')
    printf '%-14s %-9s canary -> %-9s %s (probe visibility)\n' "$a" "$(provider_of "$wb" "$wm")" "$wb" "$wm"
    changed=$((changed+1))
    [ "$ACTION" = plan ] && continue
    place_agent "$a" "$wb" "$wm" || echo "    ! canary placement failed"
  done
fi

# Contributors reconcile on the SAME probe as the agents, in the same run, so
# there is one measurement and one decision per tick rather than two views of
# headroom that can disagree.
echo
echo "contributors:"
reconcile_contributors

[ "$ACTION" = plan ] && [ "$changed" -gt 0 ] && echo && echo "$changed change(s) — run '$0 apply' to perform them"
[ "$changed" -eq 0 ] && echo && echo "fleet already on the best available rung"
exit 0
