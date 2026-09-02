#!/usr/bin/env bash
# hive-rotate.sh — capability-preserving backend rotation for the tuna-os Hive.
#
# WHY THIS EXISTS
# ---------------
# Hive's `governor.budget` counts tokens against a number YOU configure. It has
# no idea about the Claude Max weekly limit, the ChatGPT Plus weekly limit, or
# the DeepSeek credit balance — and those are what actually stop work. They are
# per-ACCOUNT, and only each client knows its own headroom.
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
#
# Env:
#   HIVE_ROTATE_THRESHOLD  rotate off a provider at/above this % used (default 85)
#   HIVE_PEAK_PROVIDERS    providers treated as unavailable during peak windows
#   HIVE_PEAK_WINDOWS      UTC HH:MM-HH:MM,... when those providers are avoided
#                          (weekdays only since DeepSeek's 2026-08-23 policy
#                          change: weekends are all-day off-peak)
#   HIVE_ROTATE_METERED_FAILOVER=0  retain the old high-volume strand-on-exhaustion policy
#   HIVE_ROTATE_DRYRUN=1   force plan-only


# Hive runs on the AWS Talos cluster; override to point elsewhere.
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
LABEL=app.kubernetes.io/name=hive
API=http://127.0.0.1:3002
STATE_DIR="${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}"
THRESHOLD="${HIVE_ROTATE_THRESHOLD:-85}"
PEAK_PROVIDERS="${HIVE_PEAK_PROVIDERS:-deepseek}"
PEAK_WINDOWS="${HIVE_PEAK_WINDOWS:-01:00-04:00,06:00-10:00}"

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
# The headline consequence: deepseek-v4-flash (82.7) OUTSCORES Sonnet 5 under
# Claude Code (74.6) and GPT-5.6 Luna under Codex (75.7) while being by far the
# cheapest. DeepSeek is therefore the DEFAULT rung on both cost and capability;
# Anthropic/OpenAI are FAILOVER rungs, not premium upgrades.
#
# DO NOT put deepseek-v4-pro above v4-flash. "Pro" is the bigger, pricier model
# and the intuitive frontier pick, but on AGENT benchmarks it loses to Flash and
# costs 3.1x more:
#     V4-Flash  TB2.1 82.7   $0.14 in / $0.28 out per 1M
#     V4-Pro    TB2.1 72.1   $0.435 in / $0.87 out per 1M   (V4-Pro-Preview)
# DeepSeek's own release notes state it plainly: "Do not switch to V4-Pro for
# agent work on price grounds alone — Flash now leads on the published agent
# suites." A third-party list did report a later "V4 Pro 0813" at 87.9, but that
# is unconfirmed by a second source and it is unclear which build the
# `deepseek-v4-pro` API id resolves to — so the vendor's explicit agentic
# guidance wins until that is settled. Flash is therefore the DeepSeek rung at
# BOTH T1 and T2: at 82.7 it is competitive with the frontier subscription
# models while costing a fraction, which is exactly what a metered default rung
# should be.
#
# Format: tier|provider|backend|model   (order within a tier = preference)
TIERS='
T1|google|agy|gemini-3.7-flash-high
T1|deepseek|pi|deepseek-v4-flash
T1|openai|codex|gpt-5.6-sol
T1|anthropic|claude|claude-opus-5
T2|google|agy|gemini-3.7-flash-low
T2|deepseek|pi|deepseek-v4-flash
T2|openai|codex|gpt-5.6-luna
T2|anthropic|claude|claude-sonnet-5
T2|google|agy|gemini-3.6-flash
T3|google|agy|gemini-3.7-flash-low
T3|deepseek|pi|deepseek-chat
T3|openai|codex|gpt-5.6-luna
T3|anthropic|claude|claude-haiku-4-5
T3|google|agy|gemini-3.6-flash
'

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

tier_members() {
  if [ "$TIER_SOURCE" = api ]; then
    awk -F'\t' -v t="$1" '!/^#/ && $1==t {print $1"|"$2"|"$3"|"$4}' "$TIER_CACHE"
  else
    printf '%s\n' "$TIERS" | awk -F'|' -v t="$1" '$1==t{print}'
  fi
}

# ── Pod + owner session ─────────────────────────────────────────────────
POD=$(kubectl get pods -n "$NS" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$POD" ] || { echo "ERROR: no hive pod found" >&2; exit 1; }

# Pick the owner session with the LATEST expiry — do not try to decide locally
# whether it is expired.
#
# The previous filter compared ExpiresAt against `date -Is` as STRINGS, and the
# two carry different UTC offsets: the store writes the hive pod's offset
# (…-04:00) while `date -Is` writes the caller's (+05:30 on a workstation,
# +00:00 in-cluster). Lexicographic comparison across differing offsets is only
# accidentally right — it happens to work while expiry is weeks away and would
# silently start discarding live sessions, or keeping dead ones, near the
# boundary. Moving this script into the cluster changes the offset, so the
# latent bug would have shipped with the move.
#
# The newest session is the best candidate regardless of what any local clock
# thinks, and the server is the only authority on whether it is still valid —
# so use it and let a real call decide. hive_api surfaces the auth failure.
SID=$(kubectl exec -n "$NS" "$POD" -- cat /data/dashboard-sessions.json 2>/dev/null \
      | jq -r '
          to_entries | map(select(.value.Role=="owner"))
          | sort_by(.value.ExpiresAt) | reverse | .[0].key // empty' 2>/dev/null)
if [ -z "$SID" ]; then
  echo "ERROR: no owner session in the dashboard session store." >&2
  echo "       Log in at https://hive.tunaos.org as an authorized_users member." >&2
  exit 1
fi

hive_api() {
  kubectl exec -n "$NS" "$POD" -- \
    curl -sS -X "$1" --max-time 25 -H "Cookie: hive_session=$SID" "$API$2" 2>&1
}
# Run a command inside the pod as a given agent's unix user.
as_agent() { kubectl exec -n "$NS" "$POD" -- su -s /bin/sh "hive-$1" -c "$2" 2>/dev/null; }

# Snapshot taken ONCE per run; every decision below reads from it.
#
# STALENESS: /api/status lags a mutation by more than 10s — a switch/model_set
# applied immediately before this fetch may still report the OLD rung. Running
# two mutating passes back to back therefore makes the second one decide on
# pre-mutation state. On the intended cadence (a timer every N minutes) this is
# a non-issue, and the failure mode is benign either way: a stale read causes a
# MISSED correction on this tick, never a wrong mutation, because a change is
# only made when the observed rung is unusable. Do not chain apply runs.
STATUS_JSON=$(hive_api GET /api/status)
printf '%s' "$STATUS_JSON" | jq -e '.agents' >/dev/null 2>&1 \
  || { echo "ERROR: could not read /api/status -> ${STATUS_JSON:0:200}" >&2; exit 1; }

agent_field() { printf '%s' "$STATUS_JSON" | jq -r --arg a "$1" --arg f "$2" '.agents[]|select(.name==$a)|.[$f]//""'; }
agent_names() { printf '%s' "$STATUS_JSON" | jq -r '.agents[].name'; }

provider_of() {  # backend model -> provider
  local c m; c=$(printf '%s' "$1" | tr 'A-Z' 'a-z'); m=$(printf '%s' "$2" | tr 'A-Z' 'a-z')
  # cli takes precedence over model-name sniffing for backends whose auth is
  # tied to the CLI, not the model it happens to be puppeting. copilot can
  # serve claude/gpt/gemini-named models through a GitHub subscription, and
  # its device-flow login is a completely different (unautomatable, never
  # headlessly recoverable) failure domain from an actual anthropic/openai/
  # google outage. Matching on model name here would let a copilot
  # login-required pause poison LOGIN_BLOCKED for a real provider and wedge
  # the whole fleet's rotation off it.
  case "$c" in copilot) echo github; return;; esac
  case "$m" in *deepseek*) echo deepseek; return;; *claude*|*opus*|*sonnet*|*haiku*) echo anthropic; return;;
               *gpt-*|*codex*) echo openai; return;; *gemini*) echo google; return;; esac
  case "$c" in claude|litellm) echo anthropic;; codex) echo openai;; agy) echo google;;
               bob) echo ibm;; pi|goose) echo deepseek;; *) echo unknown;; esac
}

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

# tmux socket for an agent (hive uses a per-user socket named after the user)
tmux_sock() { local u="hive-$1"; local uid; uid=$(as_agent "$1" 'id -u'); echo "/tmp/tmux-$uid/$u"; }

# backend_model_mismatch <backend> <model>: 0 when the pair CANNOT launch.
#
# Placement is two API calls (/api/switch then /api/model) with no transaction
# around them. When the second fails — and it does, the dashboard API times out
# under concurrent mutations — the agent is left on the NEW backend with the
# OLD model, e.g. `claude --model gemini-3.7-flash-low`. That is a hard startup
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
    *)      return 1 ;;
  esac
}

# repair_mismatch <agent>: put a mismatched agent back on a model its CURRENT
# backend can actually run, preferring its own tier's rung for that backend.
repair_mismatch() {
  local a="$1" b m tier want
  b=$(agent_field "$a" cli); m=$(agent_field "$a" govModel)
  backend_model_mismatch "$b" "$m" || return 1
  tier=$(tier_of "$a"); [ -z "$tier" ] && return 1
  want=$(tier_members "$tier" | awk -F'|' -v b="$b" '$3==b{print $4; exit}')
  [ -z "$want" ] && return 1
  printf '%-14s MISMATCH %s/%s -> setting model %s\n' "$a" "$b" "$m" "$want"
  [ "$ACTION" = plan ] && return 0
  local md; md=$(hive_api POST "/api/model/$a/$want" | jq -r '.status // .error')
  [ "$md" = "model_set" ] || printf '    ! repair failed: %s\n' "$md"
}

# ── Probes ──────────────────────────────────────────────────────────────
# Each returns "<pct_used> <resets>" — pct_used 0-100, or -1 if unknown.
#
# The slash-command probes render a FULL-SCREEN OVERLAY that must be dismissed
# with Escape, or the pane classifier reads the agent as not-ready afterwards.

probe_deepseek() {
  local out avail bal
  out=$(kubectl exec -n "$NS" "$POD" -- sh -c \
        'curl -sS --max-time 20 -H "Authorization: Bearer $DEEPSEEK_API_KEY" https://api.deepseek.com/user/balance' 2>/dev/null)
  # jq's `//` treats false as empty, which turned DeepSeek's explicit
  # {"is_available":false} exhaustion response into an "unknown" probe.
  # Test key presence instead so false survives as the string "false".
  avail=$(printf '%s' "$out" | jq -r 'if has("is_available") then .is_available else empty end' 2>/dev/null)
  bal=$(printf '%s' "$out"  | jq -r '.balance_infos[0].total_balance // empty' 2>/dev/null)
  [ -z "$avail" ] && { echo "-1 unknown"; return; }
  # Prepaid credit, not a percentage: treat "unavailable" or <$1 as exhausted.
  if [ "$avail" != "true" ]; then echo "100 balance=${bal:-0}"; return; fi
  awk -v b="${bal:-0}" 'BEGIN{ printf "%d balance=$%s\n", (b+0 < 1 ? 100 : 0), b }'
}

# pane_is_live: does this agent's pane hold a running CLI, or has it fallen back
# to a bare shell?
#
# The probes below type slash commands into the pane. If the CLI has died, those
# keystrokes go to BASH — observed live, filling a dead agent's shell with
# "/status: No such file or directory". Never type into a pane that is sitting at
# a shell prompt.
pane_is_live() {
  local a="$1" last
  last=$(as_agent "$a" "tmux -S $(tmux_sock "$a") capture-pane -pt hive-$a -S -8" \
         | grep -v '^[[:space:]]*$' | tail -1)
  [ -z "$last" ] && return 1
  # A shell prompt ends in $ or # (optionally with trailing whitespace), and
  # these agents' prompts carry the user@host:path form.
  case "$last" in
    *'$'|*'$ '|*'#'|*'# ') return 1 ;;
    *"@"*":"*"$"*)         return 1 ;;
  esac
  return 0
}

probe_pane() {  # <agent> <slash-cmd> <awk-parser>
  local a="$1" cmd="$2" parser="$3" sock text
  if ! pane_is_live "$a"; then
    echo "-1 cli-not-running"
    return
  fi
  sock=$(tmux_sock "$a")
  as_agent "$a" "tmux -S $sock send-keys -t hive-$a '$cmd'" >/dev/null 2>&1
  sleep 2
  as_agent "$a" "tmux -S $sock send-keys -t hive-$a Enter" >/dev/null 2>&1
  sleep 14
  text=$(as_agent "$a" "tmux -S $sock capture-pane -pt hive-$a -S -45")
  # ALWAYS dismiss, even on parse failure, or the agent is left on an overlay.
  as_agent "$a" "tmux -S $sock send-keys -t hive-$a Escape" >/dev/null 2>&1
  printf '%s' "$text" | awk "$parser"
}

probe_anthropic() {
  # Direct OAuth usage API — the /usage pane in this claude build renders
  # session stats only and headless /status is unavailable, but Claude Code's
  # own HUD polls api.anthropic.com/api/oauth/usage with the access token from
  # ~/.claude/.credentials.json. The response carries a `limits` array
  # (session / weekly_all / weekly_scoped) with explicit percent + resets_at;
  # the binding one is the max. Requires the anthropic-beta header or it 401s.
  # The token stays inside the pod; only the summary crosses the exec boundary.
  local out pct r
  out=$(kubectl exec -n "$NS" "$POD" -- su-exec 2010 sh -c '
    TOK=$(jq -r ".claudeAiOauth.accessToken // empty" /data/home/.claude/.credentials.json 2>/dev/null)
    [ -z "$TOK" ] && { echo "-1 no-token"; exit 0; }
    curl -s --max-time 15 -H "Authorization: Bearer $TOK" \
         -H "anthropic-beta: oauth-2025-04-20" \
         https://api.anthropic.com/api/oauth/usage' 2>/dev/null)
  # An EMPTY or missing credential is not an unreadable measurement — it is
  # positive evidence the provider cannot serve. Claude Code zeroes this file
  # when a refresh fails (observed 2026-09-02: accessToken, refreshToken and
  # expiresAt all emptied after a refresh race), and reporting that as "-1
  # unknown" let provider_ok's unmeasured-so-allow rule keep placing agents on
  # a backend whose every pane said "Login expired · Please run /login".
  # 100 routes agents away and, unlike a quota cap, only a human /login clears
  # it — so say so in the note rather than implying it will reset on its own.
  case "$out" in
    -1\ no-token) echo "100 no-credential (needs an interactive /login)"; return ;;
    -1*) echo "$out"; return ;;
  esac
  pct=$(printf '%s' "$out" | jq -r 'try ([.limits[]?.percent // 0] | max) // empty' 2>/dev/null)
  r=$(printf '%s' "$out" | jq -r 'try ([.limits[]? | select(.percent != null)] | max_by(.percent) | .resets_at) // empty' 2>/dev/null)
  if [ -z "$pct" ]; then
    echo "-1 unparsed"   # 429 rate-limit or an error body: fail-open, never act
  else
    printf '%s resets=%s\n' "$pct" "$r"
  fi
}

probe_openai() {
  local a text; a=$(first_agent_on openai); [ -z "$a" ] && { echo "-1 no-agent"; return; }
  # A HARD account cap is announced in the pane itself, not in /status:
  #   "■ You've hit your usage limit. ... or try again at Sep 6th, 2026 10:35 PM."
  # Read that FIRST. Without it the /status probe returns unparsed -> "unknown",
  # and provider_ok() deliberately admits an unmeasured provider so the ladder
  # always has a way back in — which meant rotation kept filling a pool that was
  # dead for four days. Observed 2026-09-02: 8 of 11 agents parked on an
  # exhausted codex while the free pool sat empty. An exhaustion notice is
  # POSITIVE evidence and must outrank the unmeasured-so-allow rule.
  if pane_is_live "$a"; then
    text=$(as_agent "$a" "tmux -S $(tmux_sock "$a") capture-pane -pt hive-$a -S -60")
    if printf '%s' "$text" | grep -qiE "hit your usage limit|usage limit reached|out of credits"; then
      local when
      when=$(printf '%s' "$text" | grep -oiE 'try again at [^.]*' | head -1)
      echo "100 ${when:-account limit reached}"
      return
    fi
  fi
  # codex /status -> "Weekly limit: [####....] NN% left  (resets HH:MM on DD Mon)"
  probe_pane "$a" /status '
    /Weekly limit/ {for(i=1;i<=NF;i++) if($i ~ /%$/){gsub(/%/,"",$i); left=$i}}
    /resets/       {r=$0; sub(/.*resets/,"resets",r); gsub(/[|╰╯│]/,"",r)}
    END{ if(left=="") print "-1 unparsed"; else {gsub(/ +/," ",r); print (100-left)" "r} }'
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

# probe_google: Antigravity CLI (agy) against a Google AI Pro SUBSCRIPTION, not
# metered Gemini API credits.
#
# WRONG UNTIL 2026-08-18: this used to say "agy exposes no usage/quota command"
# and always returned unknown. It does: `agy --print "/usage"` is a structured,
# off-pane probe (no tmux, no live agent pane involved — safe to run even when
# no agent is currently placed on google) that prints stable tab-free rows:
#   Gemini Models          Weekly Limit Remaining     18%   2026-08-18T18:54:53Z
#   Gemini Models          Five Hour Limit Remaining  64%   2026-08-18T03:59:30Z
#   Claude and GPT models  Weekly Limit Remaining     100%  2026-08-25T01:15:02Z
#   Claude and GPT models  Five Hour Limit Remaining  100%  2026-08-18T06:15:02Z
# An Antigravity subscription bundles TWO independent pools — this backend only
# runs Gemini models (PR #3910), so only "Gemini Models" rows are binding; the
# "Claude and GPT models" pool is a different account's business. Take the
# lower of the weekly/five-hour remaining %, since either one stalls the agent.
#
# Requires an already-placed, already-authenticated agent to run as (agy reads
# credentials from that agent's home) — same constraint probe_anthropic and
# probe_openai have via first_agent_on. If google has zero placed agents, this
# still reports unknown; that gap is the same one open in RFC #3958 §7.1.
#
# Still verifies the BINARY EXISTS first. agy is installed into the image layer
# at /usr/local/bin, which does not survive a pod restart, and the hub accepts
# the `agy` backend regardless (PR #3910). Without this check a rotation could
# move an agent onto a backend whose binary is missing, which fails at launch —
# that happened once already.
probe_google() {
  local pod_has a out candidate
  pod_has=$(kubectl exec -n "$NS" "$POD" -- sh -c 'command -v agy >/dev/null && echo yes' 2>/dev/null)
  [ "$pod_has" = yes ] || { echo "-1 agy-binary-missing"; return; }

  # Prefer an existing Agy agent, but bootstrap the first Google rung through
  # any live agent when the operator has seeded the shared $HOME/.gemini OAuth
  # state. Requiring an already-placed Agy agent made a healthy Google pool
  # permanently unmeasurable and therefore a last-choice no-agent fallback.
  a=$(first_agent_on google)
  if [ -z "$a" ]; then
    for candidate in $(agent_names); do
      [ "$(agent_field "$candidate" paused)" = true ] && continue
      if pane_is_live "$candidate"; then a="$candidate"; break; fi
    done
  fi
  [ -z "$a" ] && { echo "-1 no-agent"; return; }
  out=$(as_agent "$a" "HOME=/data/home agy --print '/usage' --output-format text")
  printf '%s' "$out" | awk '
    /^Gemini Models/ {
      if (match($0, /[0-9]+%/)) { pct = substr($0, RSTART, RLENGTH-1) }
      if (match($0, /[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z/)) { r = substr($0, RSTART, RLENGTH) }
      if (pct != "" && (best == "" || pct+0 < best+0)) { best = pct; bestr = r }
      pct = ""; r = ""
    }
    END { if (best == "") print "-1 unparsed"; else print (100-best)" resets="bestr }'
}

# ── Gather headroom ─────────────────────────────────────────────────────
declare -A PCT NOTE
gather() {
  local r
  for p in deepseek anthropic openai google; do
    case $p in
      deepseek)  r=$(probe_deepseek) ;;
      anthropic) r=$(probe_anthropic) ;;
      openai)    r=$(probe_openai) ;;
      google)    r=$(probe_google) ;;
    esac
    PCT[$p]=${r%% *}; NOTE[$p]=${r#* }
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
# cheaper, preferred first). This deliberately INVERTS the old
# "metered-before-subscription" rule: that treated DeepSeek as the cheap base
# load, but DeepSeek is the ONLY pool that burns real prepaid money, while
# agy is FREE and claude/codex are subscriptions whose caps reset for free.
#
#   google    (agy)     rank 0 — FREE. No money spend at all; the cap resets
#                                and is free again.
#   anthropic (claude)  rank 1 — subscription with a HIGH limit: low shared-cap
#                                risk, safe to lean on.
#   openai    (codex)   rank 2 — subscription with a LOW limit, shared with the
#                                operator's own interactive CLI: protect it.
#   deepseek            rank 3 — metered: every token is real money from
#                                prepaid credit. The availability insurance
#                                (no hard cap), spent last, not first.
#
# Consequence: a high-cadence agent is barred ONLY from codex during normal
# operation (the pool most likely to strand the operator too). agy and claude
# are open to it — agy costs nothing and claude's cap is generous — each still
# subject to its own exhaustion threshold and the agy 5h-window cap below.
provider_cost_rank() {
  case "$1" in
    google)    echo 0 ;;
    anthropic) echo 1 ;;
    openai)    echo 2 ;;
    deepseek)  echo 3 ;;
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
WATCHDOG_KICK_INTERVAL_MIN="${HIVE_WATCHDOG_KICK_INTERVAL_MIN:-5}"
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

cadence_s() { printf '%s' "$STATUS_JSON" | jq -r --arg a "$1" '.agents[]|select(.name==$a)|.cadence//""' \
                | awk '{ s=$0; n=s; sub(/[a-z]$/,"",n);
                         if (s ~ /h$/) print n*3600; else if (s ~ /m$/) print n*60;
                         else if (s ~ /s$/) print n+0; else print 999999 }'; }

# provider_threshold: how deep each pool may be consumed before rotation treats
# it as full. Generous limits ride higher; codex's low shared limit cuts off
# earlier. DeepSeek is balance-driven — the probe already reports 100% when the
# account is unavailable or below $1, so its threshold is moot but explicit.
provider_threshold() {
  case "$1" in
    openai)    echo "${HIVE_ROTATE_OPENAI_THRESHOLD:-85}" ;;
    anthropic) echo "${HIVE_ROTATE_CLAUDE_THRESHOLD:-90}" ;;
    google)    echo "${HIVE_ROTATE_AGY_THRESHOLD:-90}" ;;
    deepseek)  echo 100 ;;
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
#   1. provider COST rank — free (agy) first, then generous-limit claude, then
#      protected codex, then real-money DeepSeek last. The old "metered before
#      subscription" rule spent prepaid money to save caps; the inverted ladder
#      spends free/abundant quota first and money last.
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

# DeepSeek is the only no-cap availability net and every token is real money:
# warn before a low balance strands the fleet again (as -$0.00 did).
deepseek_reserve_warning() {
  local bal
  case "${NOTE[deepseek]:-}" in *balance=*) bal=${NOTE[deepseek]#*balance=} ;; *) return 0 ;; esac
  [ "$(awk -v b="$bal" 'BEGIN{gsub(/[$]/,"",b); print b+0}')" -lt 2 ] 2>/dev/null \
    && echo "WARN: DeepSeek balance $bal is below the \$2 reserve — top up soon"
}

# ── Actions ─────────────────────────────────────────────────────────────
# deepseek_reserve_warning etc. are defined above; gather must run before
# any action that reads probes.
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
contrib_provider() {
  local d="$1" b m
  b=$(kubectl get deploy -n "$CONTRIB_NS" "$d" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="AGENT_BACKEND")].value}' 2>/dev/null)
  m=$(kubectl get deploy -n "$CONTRIB_NS" "$d" -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="AGENT_MODEL")].value}' 2>/dev/null)
  [ -z "$b" ] && { echo unknown; return; }
  provider_of "$b" "$m"
}

reconcile_contributors() {
  local ds d p want have
  ds=$(kubectl get deploy -n "$CONTRIB_NS" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
  [ -z "$ds" ] && { echo "no contributor deployments in $CONTRIB_NS"; return 0; }
  for d in $ds; do
    p=$(contrib_provider "$d")
    have=$(kubectl get deploy -n "$CONTRIB_NS" "$d" -o jsonpath='{.spec.replicas}' 2>/dev/null)
    have=${have:-0}
    if provider_exhausted "$p"; then
      want=0
    elif provider_recovered "$p"; then
      want=1
    else
      # Unknown headroom: leave the worker exactly as it is. Scaling up on an
      # unmeasured provider re-creates the task-thrash this exists to stop, and
      # scaling down on one would park a worker that may be perfectly fine.
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
    kubectl scale deploy -n "$CONTRIB_NS" "$d" --replicas="$want" >/dev/null 2>&1 \
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
  local a="$1" text last
  text=$(as_agent "$a" "tmux -S $(tmux_sock "$a") capture-pane -pt hive-$a" 2>/dev/null)
  [ -z "$(printf '%s' "$text" | grep -v '^[[:space:]]*$')" ] && { echo empty; return; }
  # auth/onboarding screens: the CLI is up but cannot work. Patterns are the
  # exact CLI chrome only (agy accent/terms picker, claude login prompts) —
  # loose words like "login"/"sign in" appear in issue bodies the agent is
  # reading and caused false-positive kills (§10a lesson, RFC #4665).
  # 'please use /login to sign in to use copilot' is Copilot CLI's EXACT
  # chrome (verified against a real stuck pane 2026-09-02) — distinct wording
  # from claude's "run /login"/"not logged in", so it needs its own pattern or
  # a copilot pane sits misclassified as ready forever (confirmed: the
  # watchdog logged "liveness ok" every 5min for 43h straight while /api/status
  # reported PaneShowsLogin the whole time).
  #
  # A dismissible FIRST-RUN WIZARD is classified separately from a login, and
  # deliberately so. Every agent's ~/.gemini is a SYMLINK to the shared
  # /data/home/.gemini, so when one agent writes
  # antigravity-cli/cache/onboarding.json mode 600, every OTHER agent gets
  # EACCES and re-enters agy's theme/ToS/trust wizard. Lumping that in with
  # `auth` made the watchdog rotate the agent OFF google onto a metered
  # provider. Observed 2026-09-02: agents placed on the FREE pool were
  # evacuated to Anthropic within minutes, repeatedly, which is how a weekly
  # subscription cap burned at ~10%/hour while agy sat at 29% used. The right
  # response is to repair the shared-home permissions and relaunch on the SAME
  # rung — never to abandon a healthy provider over a dialog box.
  if printf '%s' "$text" | grep -qiE '\[next\]|\[previous\]|terms of service & data use|accent: highlighted|enter toggl|choose your color scheme|do you trust the contents|i trust this folder|welcome to (the )?antigravity'; then
    echo wizard; return
  fi
  if printf '%s' "$text" | grep -qiE 'login expired|run /login|not logged in|please run /login|please use /login|select login method|sign in to use'; then
    echo auth; return
  fi
  # shell prompt = the CLI died and the pane fell back to bash.
  if ! pane_is_live "$a"; then echo shell; return; fi
  echo ready
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
  # 1) Shared-state hygiene: agents share $HOME, and agy rewrites its
  # settings/onboarding files as mode 600 owned by the writing agent, so the
  # next launch hits EACCES and falls into the onboarding trap. Normalize the
  # shared tree each pass (the durable fix is umask 007 at launch, RFC #4665).
  # Directories are 2770, not 770: the setgid bit makes everything created
  # inside inherit the `node` group, which is what keeps a file written by one
  # agent readable by the next even before this sweep runs again.
  # The same treatment is needed for codex's per-agent state dirs. Rotation
  # moves agents across backends, so /data/home/.codex-<agent> ends up holding
  # sqlite files owned by whichever agent last ran there, at mode 644 — and the
  # agent that owns the directory then cannot write its own state:
  #   "attempt to write a readonly database ... state_5.sqlite"
  # codex dies at launch, the pane falls to a bare shell, and the watchdog
  # churns on it forever. Observed 2026-09-02 on sec-check and outreach, whose
  # dirs held files owned by hive-strategist / hive-quality / hive-supervisor.
  gemini_hygiene() {
    kubectl exec -n "$NS" "$POD" -- sh -c '
      find /data/home/.gemini/antigravity-cli -type f -exec chmod 660 {} + 2>/dev/null
      find /data/home/.gemini/antigravity-cli -type d -exec chmod 2770 {} + 2>/dev/null
      chown -R dev:node /data/home/.gemini/antigravity-cli 2>/dev/null
      for d in /data/home/.codex-*; do
        [ -d "$d" ] || continue
        chown -R dev:node "$d" 2>/dev/null
        find "$d" -type f -exec chmod 660 {} + 2>/dev/null
        find "$d" -type d -exec chmod 2770 {} + 2>/dev/null
      done' 2>/dev/null
  }
  gemini_hygiene

  # 2) Per-agent liveness: classify the pane and heal broken agents with the
  # kill-then-kick sequence (a direct kick of a wedged TUI hangs the API).
  # Exponential backoff is the k8s CrashLoopBackOff analog: skip agents we
  # kicked recently so a heal loop doesn't become a restart storm.
  healed=0
  for a in $(agent_names); do
    [ "$(agent_field "$a" paused)" = true ] && continue
    # Repair an unlaunchable backend/model pair BEFORE judging liveness, and
    # regardless of what the pane shows. A mismatch is config drift, not a pane
    # state: the currently-running process may still be happily executing the
    # OLD model, so the pane reads `ready` and the agent is skipped — right up
    # until the next kick relaunches it with the foreign model name and it dies.
    # Catching it here fixes it while it is still cheap, and catches mismatches
    # from ANY source (a timed-out /api/model, a hand-run curl), not just from
    # this script's own rotations.
    if repair_mismatch "$a"; then
      healed=$((healed+1))
      continue
    fi
    state=$(pane_classify "$a")
    [ "$state" = ready ] && { printf '%-14s liveness ok\n' "$a"; continue; }
    lk="$STATE_DIR/watchdog-last-kick-$a"
    if [ -f "$lk" ] && [ $(( $(date +%s) - $(cat "$lk") )) -lt $(( WATCHDOG_KICK_INTERVAL_MIN * 60 )) ]; then
      printf '%-14s %-8s (recently healed, backing off)\n' "$a" "$state"
      continue
    fi
    printf '%-14s %-8s -> healing (kill + kick)\n' "$a" "$state"
    # A wizard is a DIALOG, not a dead backend: repair the shared-home
    # permissions that put the agent there and relaunch on the SAME rung.
    # Rotating here is what evacuated agents off the free pool onto a metered
    # one (see pane_classify). Re-running hygiene immediately before the kick
    # matters — the sweep at the top of this pass may predate the launch that
    # re-created onboarding.json mode 600.
    if [ "$state" = wizard ]; then
      gemini_hygiene
      printf '%-14s %-8s shared-home perms repaired; relaunching in place\n' "$a" "$state"
    fi
    # If the failure is backend-level (auth chrome, or a crash-looping rung),
    # restarting on the same backend just re-breaks the agent. Rotate onto a
    # positively-measured-healthy rung first, then kick.
    if [ "$state" = auth ]; then
      tier=$(tier_of "$a")
      want=$(choose_rung_healthy "$tier" "$a")
      if [ -n "$want" ]; then
        IFS='|' read -r wp wb wm <<< "$want"
        curb=$(agent_field "$a" cli); curm=$(agent_field "$a" govModel)
        if [ "$wb" != "$curb" ] || [ "$wm" != "$curm" ]; then
          sw=$(hive_api POST "/api/switch/$a/$wb" | jq -r '.status // .error')
          if [ "$sw" = "switched" ]; then
            md=$(hive_api POST "/api/model/$a/$wm" | jq -r '.status // .error')
            if [ "$md" = "model_set" ]; then
              printf '%-14s %-8s rotated off -> %s %s\n' "$a" "$state" "$wb" "$wm"
            else
              # Roll the backend BACK rather than leave `claude --model
              # gemini-…`, which cannot start at all. A failed rotation that
              # leaves the agent where it was is recoverable; one that leaves an
              # unlaunchable pair is not.
              rb=$(hive_api POST "/api/switch/$a/$curb" | jq -r '.status // .error')
              printf '%-14s %-8s ! model set failed (%s) — rolled back to %s (%s)\n' \
                "$a" "$state" "$md" "$curb" "$rb"
            fi
          else
            printf '%-14s %-8s ! rotate failed: %s — kicking anyway\n' "$a" "$state" "$sw"
          fi
        fi
      fi
    fi
    u=$(as_agent "$a" 'id -u' 2>/dev/null)
    as_agent "$a" "tmux -S /tmp/tmux-$u/hive-$a send-keys -t hive-$a C-c 2>/dev/null; sleep 1; tmux -S /tmp/tmux-$u/hive-$a send-keys -t hive-$a C-c 2>/dev/null" 2>/dev/null
    sleep 2
    hive_api POST "/api/kick/$a" >/dev/null 2>&1 &
    echo "$(date +%s)" > "$lk"
    healed=$((healed+1))
    # Serialize: the dashboard API wedges when several agents heal at once
    # (observed: empty switch/model responses). Give each heal room to settle.
    sleep 10
  done
  echo "watchdog: $healed agent(s) healed"
  exit 0
fi

# publish_usage: mirror the probe results into a ConfigMap the in-cluster
# hive-console reads. openai and google headroom is ONLY readable by typing a
# slash command into a live CLI pane (probe_openai / probe_google), which a
# plain HTTP service has no way to do — so the console shows what this timer
# last measured, alongside updated_at so a stale reading is visibly stale
# rather than quietly wrong. Best-effort: never let a publish failure affect
# rotation, which is the job that actually matters.
publish_usage() {
  local args=() p v
  for p in deepseek anthropic openai google; do
    v="${PCT[$p]}"
    if [ "$v" = "-1" ]; then v="unknown"; else v="${v}% used"; fi
    args+=("--from-literal=$p=$v ${NOTE[$p]}")
  done
  kubectl create configmap hive-provider-usage -n "$NS" \
    "${args[@]}" "--from-literal=updated_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --dry-run=client -o yaml 2>/dev/null | kubectl apply -f - >/dev/null 2>&1 \
    || echo "WARN: could not publish provider usage ConfigMap" >&2
}

if [ "$ACTION" = probe ]; then
  printf '%-11s %-9s %s\n' PROVIDER USED NOTE
  for p in deepseek anthropic openai google; do
    v="${PCT[$p]}"; [ "$v" = "-1" ] && v="unknown" || v="${v}%"
    printf '%-11s %-9s %s\n' "$p" "$v" "${NOTE[$p]}"
  done
  in_peak_window && echo && echo "peak window ACTIVE (UTC $(date -u +%H:%M)); avoiding: $PEAK_PROVIDERS"
  deepseek_reserve_warning
  publish_usage
  exit 0
fi

# The apply/plan paths have already gathered the same probe data, so publish
# from here too — otherwise the console's google/openai rows would only ever
# refresh on a manual `probe` run.
publish_usage

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
    md=$(hive_api POST "/api/model/$a/$m" | jq -r '.status // .error')
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
if [ "${HIVE_ROTATE_AUTORESUME:-1}" = 1 ]; then
  for a in $(agent_names); do
    [ "$(agent_field "$a" paused)" = true ] || continue
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

changed=0
for a in $(agent_names); do
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
  if ! provider_exhausted "$curp" && ! provider_login_blocked "$curp" &&
     rung_in_tier "$tier" "$curb" "$curm"; then
    note_placement "$curp" "$a"
    printf '%-14s %-9s %s ok\n' "$a" "$curp" "$curm"
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

  # Switch FIRST, and check it: a switch that fails while the model succeeds
  # leaves the agent on the old backend with a foreign model name, which is a
  # hard startup failure (e.g. `pi --model gemini-3.6-flash`).
  sw=$(hive_api POST "/api/switch/$a/$wb" | jq -r '.status // .error')
  if [ "$sw" != "switched" ]; then
    echo "    ! switch failed: $sw — leaving $a alone"; continue
  fi
  md=$(hive_api POST "/api/model/$a/$wm" | jq -r '.status // .error')
  if [ "$md" != "model_set" ]; then
    # Same reasoning as the watchdog path: never leave the agent on a new
    # backend with the previous backend's model — that pair cannot launch.
    rb=$(hive_api POST "/api/switch/$a/$curb" | jq -r '.status // .error')
    echo "    ! model set failed: $md — rolled back to $curb ($rb)"
    continue
  fi
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
CANARY_COOLDOWN_MIN="${HIVE_ROTATE_CANARY_COOLDOWN_MIN:-120}"
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
    sw=$(hive_api POST "/api/switch/$a/$wb" | jq -r '.status // .error')
    if [ "$sw" != "switched" ]; then
      echo "    ! canary switch failed: $sw"; continue
    fi
    md=$(hive_api POST "/api/model/$a/$wm" | jq -r '.status // .error')
    [ "$md" = "model_set" ] || echo "    ! canary model set failed: $md"
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
