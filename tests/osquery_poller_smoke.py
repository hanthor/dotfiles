#!/usr/bin/env python3
"""Prove real listener drift reaches the scheduled poller's private snapshot.

Briefly pauses only the poll timer to avoid racing a second poll. Host baselines
are never accepted or edited; the listener and normal polling are restored.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess


POLL = "fleet-osquery-poll.service"
TIMER = "fleet-osquery-poll.timer"
BASELINE = Path("/var/lib/fleet-osquery/baseline.json")


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=300).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo: host reports are root-private.")
    original = BASELINE.read_bytes()
    timer_active = subprocess.run(["systemctl", "is-active", "--quiet", TIMER], check=False).returncode == 0
    sock = socket.socket()

    def poll_local_report():
        command("/opt/fleet-osquery/fleet-osquery", "report")
        command("systemctl", "start", POLL)
        snapshot = json.loads(args.snapshot.read_text())
        assert args.snapshot.stat().st_mode & 0o077 == 0, "aggregate snapshot is not private"
        assert args.snapshot.parent.stat().st_mode & 0o077 == 0, "aggregate directory is not private"
        return next(item["report"] for item in snapshot["hosts"]
                    if item.get("report", {}).get("host") == socket.gethostname())

    def contains_listener(report, port):
        return any(row["address"] == "127.0.0.1" and row["port"] == str(port)
                   and row["protocol"] == "6"
                   for row in report["changes"]["listening_ports"]["added"])

    try:
        if timer_active:
            command("systemctl", "stop", TIMER)
        command("systemctl", "stop", POLL)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert contains_listener(poll_local_report(), port), "poller missed real listener drift"
        assert BASELINE.read_bytes() == original, "poller accepted pending drift"
        sock.close()
        assert not contains_listener(poll_local_report(), port), "poller retained a removed temporary listener"
        assert BASELINE.read_bytes() == original, "poller changed the host baseline"
        print("PASS: real listener drift reaches the private aggregate and clears after removal; baseline unchanged")
    finally:
        sock.close()
        try:
            # Remove the fixture from cached host/fleet reports even on failure.
            poll_local_report()
        finally:
            if timer_active:
                command("systemctl", "start", TIMER)
    print("PASS: temporary listener removed and original poll timer state restored")


if __name__ == "__main__":
    main()
