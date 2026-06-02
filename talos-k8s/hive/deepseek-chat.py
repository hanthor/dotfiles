#!/usr/bin/env python3
"""DeepSeek chat CLI — OpenAI-compatible loop for hive agent sessions.

Replaces goose as the hive backend. Reads prompts from stdin
(command-line args first, then interactive stdin loop).

Usage:
    deepseek-chat [--model deepseek-v4-pro] [--prompt "initial prompt"]

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
    """Send a single chat completion request to DeepSeek."""
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

    # Parse CLI args (hive passes --model and --prompt)
    args = sys.argv[1:]
    initial_prompts = []
    i = 0
    while i < len(args):
        if args[i] == "--model" and i + 1 < len(args):
            model = args[i + 1]
            i += 2
        elif args[i] == "--prompt" and i + 1 < len(args):
            initial_prompts.append(args[i + 1])
            i += 2
        elif args[i] == "--no-confirm":
            i += 1  # hive compat, ignore
        else:
            i += 1

    if not api_key:
        print("Error: DEEPSEEK_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    print(f"DeepSeek chat ready (model: {model})", flush=True)
    print("Environment loaded", flush=True)  # AGENT_READY_MARKER for hive

    # Process initial prompts from command line
    for prompt in initial_prompts:
        if prompt.strip():
            response = chat(prompt, api_key, api_host, model)
            print(response, flush=True)

    # Interactive stdin loop — read prompts line by line
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

        # Skip hive internal directives
        if line.startswith("/clear"):
            continue

        response = chat(line, api_key, api_host, model)
        print(response, flush=True)


if __name__ == "__main__":
    main()
