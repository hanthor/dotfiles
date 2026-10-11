#!/usr/bin/env bash
# Smoke-test each omp provider with a one-word prompt, then show remaining
# quota via ccleft. Exact model ids are used: omp fuzzy-matches short names
# to old models (e.g. "claude-sonnet" -> claude-sonnet-4-0, which 404s).
set -uo pipefail

TESTS=(
  "anthropic/claude-haiku-5-5"
  "openai-codex/gpt-5.6-luna"
  "google-antigravity/claude-sonnet-5-5"
  "meta/muse-spark-1.3"
  "kiro/claude-sonnet-4.5"
)

fail=0
for m in "${TESTS[@]}"; do
  out=$(timeout 90 omp -p --no-session --model "$m" "reply with just: ok" 2>&1)
  if grep -qi '^ok' <<<"$out"; then
    printf '  ✓ %s\n' "$m"
  else
    printf '  ✗ %s: %s\n' "$m" "$(tail -1 <<<"$out" | cut -c1-160)"
    fail=1
  fi
done

echo
CCLEFT="$(command -v ccleft || echo "$HOME/go/bin/ccleft")"
if [ -x "$CCLEFT" ]; then
  "$CCLEFT" probe
else
  echo "ccleft not installed — run: just apply-tags omp"
fi
exit $fail
