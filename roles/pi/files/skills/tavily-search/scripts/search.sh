#!/usr/bin/env bash
# Tavily AI Search — wrapper for https://api.tavily.com/search
set -euo pipefail

API_KEY="${TAVILY_API_KEY:?TAVILY_API_KEY not set — see ~/.config/shell/secrets.sh}"
API_URL="https://api.tavily.com/search"
MAX_RESULTS=5
DEPTH="basic"

usage() {
  echo "Usage: $0 <query> [--max N] [--depth basic|advanced]"
  exit 1
}

[ $# -eq 0 ] && usage
QUERY="$1"
shift

while [ $# -gt 0 ]; do
  case "$1" in
    --max) MAX_RESULTS="$2"; shift 2 ;;
    --depth) DEPTH="$2"; shift 2 ;;
    *) usage ;;
  esac
done

curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg q "$QUERY" \
    --argjson max "$MAX_RESULTS" \
    --arg depth "$DEPTH" \
    --arg api_key "$API_KEY" \
    '{api_key: $api_key, query: $q, max_results: $max, search_depth: $depth}')" \
  | jq '.results[] | {title, url, content: .content[0:200]}'
