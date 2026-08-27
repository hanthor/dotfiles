#!/usr/bin/env bash
# hive-tiers.sh — regenerate hive-rotate.sh's capability tiers from a live
# third-party benchmark API instead of a hand-maintained table.
#
# WHY
# ---
# Hardcoded tiers go stale the moment a vendor ships. Worse, they encode a
# guess: vendor tier NAMES ("flash", "pro", "sonnet") do not line up across
# providers, and assuming they do is how you end up rotating an agent onto a
# model that scores 8 points lower. Sourcing the ranking externally makes the
# ladder self-maintaining and auditable.
#
# SOURCE
# ------
# Artificial Analysis Data API — https://artificialanalysis.ai/data-api/docs
#   GET https://artificialanalysis.ai/api/v2/language/models/free
#   auth: `x-api-key` header (free tier, 1000 req/day — a weekly refresh is
#   three orders of magnitude inside that)
#
# We rank on `evaluations.artificial_analysis_agentic_index`, which is the
# closest published proxy for "can this model drive a CLI agent to completion" —
# the thing hive agents actually do. `artificial_analysis_coding_index` is
# recorded alongside it for reference.
#
# CAVEAT worth keeping in mind: this index scores MODELS, whereas hive runs
# MODEL + HARNESS pairs, and the harness is worth several points on its own
# (Gemini 3 Pro measured 73.9 under Terminus 2 vs 65.8 under Gemini CLI on
# Terminal-Bench 2.1). Treat the API ranking as the ordering signal, not as an
# absolute prediction of this fleet's accuracy.
#
# USAGE
#   hive-tiers.sh refresh    # fetch, rebuild, write the tier cache
#   hive-tiers.sh show       # print the current tier cache
#
# Key lookup order: $AA_API_KEY, then ~/.config/hive/aa-api-key.
# With no key (or on any API failure) the existing cache is kept and the exit
# code is non-zero — hive-rotate.sh then falls back to its built-in table, so a
# benchmark outage can never wedge rotation.


# Hive runs on the AWS Talos cluster; override to point elsewhere.
: "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
export KUBECONFIG

set -u

CACHE_DIR="${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}"
CACHE="$CACHE_DIR/tiers.tsv"
RAW="$CACHE_DIR/aa-models.json"
API="https://artificialanalysis.ai/api/v2/language/models/free"

mkdir -p "$CACHE_DIR"
ACTION="${1:-show}"

if [ "$ACTION" = show ]; then
  [ -s "$CACHE" ] || { echo "no tier cache at $CACHE — run '$0 refresh'" >&2; exit 1; }
  printf 'tier\tprovider\tbackend\tmodel\tagentic\t$out/M\n'
  grep -v '^#' "$CACHE"
  echo
  echo "# generated: $(grep -m1 '^# generated' "$CACHE" | cut -d' ' -f3-)"
  exit 0
fi
[ "$ACTION" = refresh ] || { echo "usage: $0 refresh|show" >&2; exit 2; }

KEY="${AA_API_KEY:-}"
[ -z "$KEY" ] && [ -r "$HOME/.config/hive/aa-api-key" ] && KEY=$(tr -d '\r\n' < "$HOME/.config/hive/aa-api-key")
if [ -z "$KEY" ]; then
  echo "ERROR: no Artificial Analysis API key." >&2
  echo "       Create one at https://artificialanalysis.ai/data-api (free tier)," >&2
  echo "       then: echo <key> > ~/.config/hive/aa-api-key && chmod 600 ~/.config/hive/aa-api-key" >&2
  echo "       Keeping existing cache; hive-rotate.sh will use its built-in table." >&2
  exit 1
fi

http=$(curl -sS --max-time 45 -w '%{http_code}' -o "$RAW.tmp" -H "x-api-key: $KEY" "$API" 2>/dev/null)
if [ "$http" != "200" ] || ! jq -e '.data' "$RAW.tmp" >/dev/null 2>&1; then
  echo "ERROR: benchmark API returned HTTP ${http:-?} — keeping existing cache." >&2
  rm -f "$RAW.tmp"; exit 1
fi
mv "$RAW.tmp" "$RAW"

# ── Creator -> (provider, backend) ──────────────────────────────────────
# Only creators whose CLI this hive can actually launch. A model we cannot run
# has no business in the ladder however well it scores.
#
# ── API slug -> the model id the CLI expects ────────────────────────────
# These are NOT the same namespace: the benchmark API has its own slugs while
# each CLI takes its vendor's own id. This translation is the one piece that
# still needs a human when a vendor ships a new model — keep it small and
# obvious rather than clever.
# GOOGLE IS DELIBERATELY EXCLUDED.
# Google access here is a Google AI Pro *subscription* driven through the
# Antigravity CLI (`agy`), not metered Gemini API credits — and there are no
# Gemini API credits on this account. So:
#   * backend `gemini` is accepted by the hub but would need API credits -> unusable
#   * backend `agy` has the credentials and works, but the hub REJECTS the name
#     ("unsupported backend \"agy\"") even though backends.conf lists it
# Emitting a google rung would therefore produce a switch that either fails
# outright or lands an agent on a backend with no way to pay for tokens.
# Re-enable this the moment the hub accepts `agy`.
jq -r '
  def provider_of($c):
    ($c | ascii_downcase) as $l
    | if   $l | test("anthropic") then "anthropic|claude"
      elif $l | test("openai")    then "openai|codex"
      elif $l | test("deepseek")  then "deepseek|pi"
      else empty end;

  # Map an API slug/name to the id the CLI wants. Falls back to the slug, which
  # is right often enough for Anthropic/DeepSeek and wrong loudly rather than
  # silently for the rest (an unknown id makes the CLI fail at launch, which the
  # rotate script reports, instead of quietly running the wrong model).
  def cli_model($slug; $name):
    $slug
    | gsub("^anthropic-"; "") | gsub("^openai-"; "")
    | gsub("^deepseek-ai-"; "") | gsub("^google-"; "");

  [ .data[]
    | select(.evaluations.artificial_analysis_agentic_index != null)
    | (provider_of(.model_creator.name)) as $pb
    | select($pb != null)
    | { provider: ($pb | split("|")[0]),
        backend:  ($pb | split("|")[1]),
        model:    cli_model(.slug; .name),
        agentic:  .evaluations.artificial_analysis_agentic_index,
        coding:   (.evaluations.artificial_analysis_coding_index // 0),
        price:    (.price_1m_output_tokens // 0) } ]
  | sort_by(-.agentic)
  # Tier by ABSOLUTE agentic score, not by rank position: rank-based tiering
  # silently promotes a weak model into T1 whenever the field thins out.
  | map(. + { tier: (if   .agentic >= 60 then "T1"
                     elif .agentic >= 40 then "T2"
                     else "T3" end) })
  # Best two rungs per (tier, provider) — enough for a preference order without
  # bloating the table with near-duplicates.
  | group_by([.tier, .provider]) | map(sort_by(-.agentic) | .[0:2]) | flatten
  | sort_by(.tier, -.agentic)
  | .[] | [.tier, .provider, .backend, .model, (.agentic|tostring), (.price|tostring)]
  | @tsv
' "$RAW" > "$CACHE.tmp" 2>/dev/null

if [ ! -s "$CACHE.tmp" ]; then
  echo "ERROR: API responded but no usable models parsed — keeping existing cache." >&2
  echo "       (schema drift? inspect $RAW)" >&2
  rm -f "$CACHE.tmp"; exit 1
fi

{ echo "# generated $(date -Is) from $API"
  echo "# tier<TAB>provider<TAB>backend<TAB>model<TAB>agentic_index<TAB>price_out_per_1M"
  cat "$CACHE.tmp"
} > "$CACHE"
rm -f "$CACHE.tmp"

echo "wrote $(grep -vc '^#' "$CACHE") rungs to $CACHE"
grep -v '^#' "$CACHE" | awk -F'\t' '{printf "  %-3s %-10s %-8s %-24s agentic=%-6s $%s/M\n",$1,$2,$3,$4,$5,$6}'
