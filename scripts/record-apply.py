#!/usr/bin/env python3
"""Record the outcome of an apply run to ~/.cache/dotfiles/last-apply.json.

Usage: record-apply.py EXIT_CODE [LABEL [SKIP_TAGS]]

Called from each apply* recipe in the Justfile right after the ansible-playbook
invocation. `just doctor` reads the file to report convergence freshness.
"""
import json
import os
import subprocess
import sys
import time


def git(*args: str) -> str:
    repo = os.path.expanduser("~/.local/share/dotfiles")
    try:
        return subprocess.check_output(
            ["git", "-C", repo, *args], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "?"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: record-apply.py EXIT_CODE [LABEL [SKIP_TAGS]]", file=sys.stderr)
        return 2

    exit_code = int(sys.argv[1])
    label = sys.argv[2] if len(sys.argv) > 2 else "apply"
    skip_tags = sys.argv[3] if len(sys.argv) > 3 else ""

    cache_dir = os.path.expanduser("~/.cache/dotfiles")
    os.makedirs(cache_dir, exist_ok=True)

    now = int(time.time())
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "epoch": now,
        "exit_code": exit_code,
        "label": label,
        "skip_tags": skip_tags,
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "--short", "HEAD"),
        "hostname": os.uname().nodename,
    }

    path = os.path.join(cache_dir, "last-apply.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
