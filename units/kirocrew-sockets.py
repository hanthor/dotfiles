#!/usr/bin/env python3
"""Reject non-loopback listening sockets owned by the kirocrew process."""
import sys


def main():
    unsafe = []
    for line in sys.stdin:
        if '"kirocrew"' not in line:
            continue
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
