---
name: searxng-search
description: Web search via self-hosted SearXNG metasearch engine at search.manatee-basking.ts.net. Use when you need to search the web for documentation, facts, or current information. Supports JSON API with DuckDuckGo, Google, Brave, Wikipedia engines.
compatibility: Requires Tailscale access to search.manatee-basking.ts.net
---

# SearXNG Search

Self-hosted privacy-respecting web search for the pi agent. Queries `https://search.manatee-basking.ts.net/search` via JSON API.

## Usage

Search the web and return top results as structured JSON:

```bash
./search.sh "your search query" [--count N] [--engines duckduckgo,google,wikipedia]
```

Returns: title, url, content snippet for each result (max 10 by default).

## Engines

Default engines: duckduckgo, google, brave, wikipedia

Override with `--engines` flag.

## Examples

```bash
./search.sh "kubernetes ingress tls configuration"
./search.sh "talos linux upgrade procedure" --count 5
./search.sh "python asyncio best practices" --engines google
```
