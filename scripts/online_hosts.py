#!/usr/bin/env python3
"""Print online fleet hosts: tailscale online peers ∩ inventory, minus vps + self.

Used by the Justfile's `_online_hosts`. Tailscale failure → empty output.
"""
import json
import os
import subprocess
import sys

INVENTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inventory.yml")


def parse_inventory(text):
    """Return (all_hosts, vps_hosts) from inventory.yml text.

    No PyYAML (not guaranteed on the system python): hosts are the 4-space keys
    under all.hosts; vps members are the 8-space keys under children.vps.hosts.
    """
    all_hosts, vps, section, group = set(), set(), None, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        key = line.strip().rstrip(":")
        if indent == 2:
            section = key
        elif indent == 4 and section == "hosts":
            all_hosts.add(key)
        elif indent == 4 and section == "children":
            group = key
        elif indent == 8 and section == "children" and group == "vps":
            vps.add(key)
    return all_hosts, vps


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
