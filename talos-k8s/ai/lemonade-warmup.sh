#!/bin/bash
# lemonade-warmup.sh — pre-download the models listed in lemonade-models.txt
# into the Lemonade server's PVC (dotfiles#28).
#
# Lemonade auto-downloads models from Hugging Face on first use via
# `POST /api/pull` (Ollama-compatible model-lifecycle endpoint documented in
# lemonade-ops.md). This script drives that endpoint for every model in
# lemonade-models.txt, so recovery from a bare/restored PVC is one script
# invocation instead of manually replaying curl commands per model.
#
# Usage:
#   ./lemonade-warmup.sh [base_url]
#
# base_url defaults to the Tailscale ingress; override for direct/LAN access
# (see "Connecting from outside the cluster" in lemonade-ops.md).
set -euo pipefail

BASE_URL="${1:-https://lemonade.manatee-basking.ts.net}"
MODELS_FILE="$(dirname "$0")/lemonade-models.txt"

if [ ! -f "$MODELS_FILE" ]; then
  echo "ERROR: $MODELS_FILE not found" >&2
  exit 1
fi

if ! curl -fsS --max-time 10 -o /dev/null "${BASE_URL}/api/version"; then
  echo "ERROR: Lemonade server unreachable at ${BASE_URL}/api/version" >&2
  exit 1
fi

FAILED=0
TOTAL=0

while IFS= read -r line; do
  # Strip comments and surrounding whitespace; skip blank lines.
  model="${line%%#*}"
  model="$(echo "$model" | xargs)"
  [ -z "$model" ] && continue

  TOTAL=$((TOTAL + 1))
  echo "== Pulling ${model} =="

  # /api/pull streams progress; -N disables buffering so it shows live.
  # Non-zero curl exit (network/HTTP failure) is caught; a model-not-found
  # error inside a 200 response body still needs the last line inspected.
  RESPONSE=$(curl -fsS -N -X POST "${BASE_URL}/api/pull" \
    -H "Content-Type: application/json" \
    -d "{\"model\": \"${model}\"}" 2>&1) || {
      echo "FAILED: ${model} (request error)" >&2
      echo "$RESPONSE" >&2
      FAILED=$((FAILED + 1))
      continue
    }

  echo "$RESPONSE" | tail -5

  if echo "$RESPONSE" | grep -qi '"error"'; then
    echo "FAILED: ${model} (server reported error)" >&2
    FAILED=$((FAILED + 1))
  fi
done < "$MODELS_FILE"

echo
echo "Warmup complete: $((TOTAL - FAILED))/${TOTAL} models pulled successfully."

if [ "$FAILED" -gt 0 ]; then
  echo "${FAILED} model(s) failed — see output above." >&2
  exit 1
fi
