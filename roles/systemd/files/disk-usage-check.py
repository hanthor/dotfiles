#!/usr/bin/env python3
"""Exit 1 when a filesystem is fuller than the threshold.

Usage: disk-usage-check.py THRESHOLD_PERCENT PATH [PATH ...]

Run by disk-usage-check.timer; a non-zero exit puts the unit in the failed
state, and its OnFailure=notify-failure@%n.service sends the alert. Paths
that do not exist, read-only filesystems (the composefs/erofs root on bootc
hosts, which always reads 100%) and repeats of one filesystem are skipped.
"""
import os
import sys


def usage_percent(st: os.statvfs_result) -> int:
    # Same formula as df: used / (used + available to non-root), rounded up.
    used = st.f_blocks - st.f_bfree
    total = used + st.f_bavail
    if total <= 0:
        return 0
    return -(-used * 100 // total)


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: disk-usage-check.py THRESHOLD_PERCENT PATH [PATH ...]", file=sys.stderr)
        return 2
    threshold = int(sys.argv[1])
    seen = set()
    full = []
    for path in sys.argv[2:]:
        try:
            dev = os.stat(path).st_dev
            st = os.statvfs(path)
        except OSError:
            continue
        if dev in seen or st.f_flag & os.ST_RDONLY:
            continue
        seen.add(dev)
        pct = usage_percent(st)
        print(f"{path}: {pct}% used")
        if pct > threshold:
            full.append(f"{path} {pct}%")
    if full:
        print(f"over {threshold}%: {', '.join(full)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
