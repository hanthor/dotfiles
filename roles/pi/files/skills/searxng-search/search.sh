#!/usr/bin/env bash
# SearXNG search — query the self-hosted metasearch engine
# Usage: ./search.sh "query" [--count N] [--engines e1,e2,e3]
set -euo pipefail

SEARXNG_URL="https://search.manatee-basking.ts.net"
QUERY=""
COUNT=10
ENGINES="duckduckgo,google,brave,wikipedia"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --count)
            COUNT="$2"
            shift 2
            ;;
        --engines)
            ENGINES="$2"
            shift 2
            ;;
        *)
            QUERY="$1"
            shift
            ;;
    esac
done

if [ -z "$QUERY" ]; then
    echo "Usage: $0 \"query\" [--count N] [--engines e1,e2]" >&2
    exit 1
fi

# URL-encode the query
ENCODED_QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${QUERY}'))")

# Search and format results
curl -sS --max-time 20 "${SEARXNG_URL}/search?q=${ENCODED_QUERY}&format=json&categories=general&engines=${ENGINES}&pageno=1" \
    | python3 -c "
import json, sys

try:
    data = json.load(sys.stdin)
except json.JSONDecodeError:
    print('Error: Invalid JSON response from SearXNG', file=sys.stderr)
    sys.exit(1)

results = data.get('results', [])
count = min(len(results), ${COUNT})

print(f'# Search: {data.get(\"query\", \"?\")}')
print(f'# Results: {len(results)} total, showing {count}')
print()

for i, r in enumerate(results[:count]):
    title = r.get('title', 'Untitled')
    url = r.get('url', '')
    content = r.get('content', '')
    # Truncate content
    if len(content) > 300:
        content = content[:297] + '...'
    print(f'## {i+1}. {title}')
    print(f'URL: {url}')
    if content:
        print(f'{content}')
    print()
" 2>&1

exit 0
