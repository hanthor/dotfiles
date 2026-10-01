#!/usr/bin/env python3
"""Print online fleet hosts: tailscale online peers ∩ inventory, minus vps + self.

Used by the Justfile's `_online_hosts`. Tailscale failure → empty output.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory_parser import parse_inventory  # noqa: E402  (re-exported for callers)

INVENTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inventory.yml")


def online_peers(status):
    """Lowercased DNS short names + HostNames of Online peers in `tailscale status --json`."""
    online = set()
    for p in ((status or {}).get("Peer") or {}).values():
        if p.get("Online"):
            online.add(p.get("DNSName", "").lower().split(".")[0])
            online.add(p.get("HostName", "").lower())
    online.discard("")
    return online


def main():
    try:
        status = json.loads(subprocess.run(["tailscale", "status", "--json"],
                                           capture_output=True, text=True, timeout=10).stdout)
    except Exception:
        status = {}
    with open(os.environ.get("DOTFILES_INVENTORY", INVENTORY)) as f:
        all_hosts, vps = parse_inventory(f.read())
    try:
        with open("/etc/dotfiles-machine") as f:
            me = f.read().strip().lower()
    except OSError:
        me = os.uname().nodename.lower()
    # Retired VPSes must never be applied to.
    all_hosts -= vps | {me, os.uname().nodename.lower()}
    print(" ".join(sorted(all_hosts & online_peers(status))))


if __name__ == "__main__":
    sys.exit(main())
