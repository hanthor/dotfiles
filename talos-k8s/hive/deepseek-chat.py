#!/usr/bin/env python3
"""DeepSeek chat CLI — OpenAI-compatible loop for hive agent sessions.

Replaces goose as the hive backend. Reads prompts from stdin,
calls DeepSeek API, writes responses to stdout.

Usage:
    deepseek-chat [--model deepseek-v4-pro]

Env vars:
    DEEPSEEK_API_KEY  — API key (required)
    DEEPSEEK_API_HOST — API endpoint (default: https://api.deepseek.com)
    DEEPSEEK_MODEL    — Model name (default: deepseek-v4-pro)
"""

import os
import sys
import json
import urllib.request
import urllib.error


def chat(prompt: str, api_key: str, api_host: str, model: str) -> str:
    """Send a single chat completion request."""
    url = f"{api_host}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        return f"API Error ({e.code}): {error_body[:500]}"
    except Exception as e:
        return f"Error: {e}"


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    api_host = os.environ.get("DEEPSEEK_API_HOST", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")

    # Parse CLI args
    args = sys.argv[1:]
    # Skip --no-confirm (hive compat)
    args = [a for a in args if a != "--no-confirm"]
    for i, a in enumerate(args):
        if a == "--model" and i + 1 < len(args):
            model = args[i + 1]
            break

    if not api_key:
        print("Error: DEEPSEEK_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"DeepSeek chat ready (model: {model})", flush=True)
    print("Environment loaded", flush=True)  # AGENT_READY_MARKER

    # Interactive loop — read prompts from stdin
    buffer = ""
    while True:
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            break
        if not line:  # EOF
            break

        line = line.strip()
        if not line:
            continue

        buffer += line + "\n"

        # Send when we have a complete prompt (ends with newline on empty line,
        # or just process each line as a separate prompt)
        # For hive's kick-agents, prompts come as single-line directives
        # prefixed with the agent's instructions.
        if not line.startswith("/") and len(buffer) > 0:
            # Flush accumulated prompt
            prompt = buffer.strip()
            if prompt:
                response = chat(prompt, api_key, api_host, model)
                print(response, flush=True)
            buffer = ""


if __name__ == "__main__":
    main()
