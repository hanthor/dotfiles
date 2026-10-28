#!/usr/bin/env python3
"""Reject non-loopback sockets belonging to Kiro Crew's systemd cgroup."""
import argparse
from pathlib import Path
import re
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cgroup")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"))
    args = parser.parse_args()
    if args.cgroup is not None and (not args.cgroup.startswith("/") or args.cgroup == "/"):
        print("invalid kirocrew service cgroup", file=sys.stderr)
        return 1
    unsafe = []
    owned = 0
    for line in sys.stdin:
        belongs = args.cgroup is None and '"kirocrew"' in line
        if args.cgroup is not None:
            for pid in re.findall(r"\bpid=(\d+)", line):
                try:
                    entries = (args.proc_root / pid / "cgroup").read_text().splitlines()
                except FileNotFoundError:
                    # The process exited while ss was enumerating sockets.
                    continue
                except OSError as error:
                    print(f"cannot inspect listener cgroup: {error}", file=sys.stderr)
                    return 1
                paths = [entry.split(":", 2)[-1] for entry in entries]
                if any(path == args.cgroup or path.startswith(args.cgroup + "/") for path in paths):
                    belongs = True
                    break
        if not belongs:
            continue
        owned += 1
        columns = line.split()
        if len(columns) < 4:
            unsafe.append(line.rstrip())
            continue
        local = columns[3]
        if not (local.startswith('127.0.0.1:') or local.startswith('[::1]:')):
            unsafe.append(line.rstrip())
    if unsafe:
        print('kirocrew is listening beyond localhost:', file=sys.stderr)
        for line in unsafe:
            print(line, file=sys.stderr)
        return 1
    if args.cgroup is not None and not owned:
        print('no listeners attributable to kirocrew; localhost-only binding cannot be verified', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
