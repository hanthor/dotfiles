#!/usr/bin/env python3
"""Pretty-print ~/.cache/dotfiles/last-apply.json for `just doctor`.

Exits non-zero if the recorded apply failed, or if its timestamp is older than
48 hours, so doctor can flag it as a problem.
"""
import json
import os
import sys
import time

PATH = os.path.expanduser("~/.cache/dotfiles/last-apply.json")
STALE_AFTER = 48 * 3600


def main() -> int:
    try:
        data = json.load(open(PATH))
    except (OSError, ValueError) as exc:
        print(f"  ⚠ could not read {PATH}: {exc}")
        return 1

    age = max(0, int(time.time()) - int(data.get("epoch", 0)))
    h, m = divmod(age // 60, 60)
    age_str = f"{h}h{m}m ago" if h else f"{m}m ago"

    rc = int(data.get("exit_code", -1))
    label = data.get("label", "apply")
    skip = data.get("skip_tags") or "(none)"
    branch = data.get("branch", "?")
    commit = data.get("commit", "?")

    icon = "✓" if rc == 0 else "⚠"
    stale = age > STALE_AFTER
    if stale:
        icon = "⚠"

    print(
        f"  {icon} {label} {age_str} at {commit} on {branch} "
        f"(rc={rc}, skipped={skip})"
    )
    if stale:
        print(f"     → stale (>{STALE_AFTER // 3600}h since last apply)")

    return 1 if (rc != 0 or stale) else 0


if __name__ == "__main__":
    sys.exit(main())
