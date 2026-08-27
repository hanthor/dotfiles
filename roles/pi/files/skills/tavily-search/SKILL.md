---
name: tavily-search
description: Web search via Tavily AI-optimized search API. Use when you need to research fixes, look up documentation, find known issues, or search the web for any technical information.
---

# Tavily Search

AI-optimized web search API. Returns relevant, clean results for research and troubleshooting.

## Usage

```bash
./search.sh "your search query" [--max N] [--depth basic|advanced]
```

Returns: title, url, content snippet for each result.

- `--max N`: number of results (default 5, max 10)
- `--depth`: basic = fast, advanced = more thorough

## API Key

API key: read from `$TAVILY_API_KEY` (provisioned by the `shell_ai` role from Bitwarden item `tavily-api-key`).

Endpoint: `https://api.tavily.com/search`
