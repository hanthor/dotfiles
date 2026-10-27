#!/usr/bin/env python3
"""Print online fleet hosts: tailscale online peers ∩ inventory, minus vps + self.

Used by the Justfile's `_online_hosts`. Tailscale failure → empty output.

`--peers` prints just the online tailnet names, one per line; both callers
share the same matching rule (online_peers).
"""
import json
import os
import re
import subprocess
import sys

INVENTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "inventory.yml")


def online_peers(status):
    """Lowercased MagicDNS short names of Online peers in `tailscale status --json`.

    HostName is only a fallback for peers without a DNSName: it is the OS
    hostname, which is not unique on the tailnet (several "localhost"s).
    """
    online = set()
    for p in ((status or {}).get("Peer") or {}).values():
        if p.get("Online"):
            name = (p.get("DNSName") or "").split(".")[0] or (p.get("HostName") or "")
            online.add(name.lower())
    online.discard("")
    return online


def tailnet_names(text):
    """{inventory host: tailnet_name} for hosts in all.hosts that set one."""
    names, section, host = {}, None, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2:
            section = line.strip().rstrip(":")
        elif indent == 4 and section == "hosts":
            host = line.strip().rstrip(":")
        elif indent == 6 and section == "hosts":
            m = re.match(r"tailnet_name:\s*(\S+)", line.strip())
            if m:
                names[host] = m.group(1).strip("'\"").lower()
    return names


def tailscale_status():
    try:
        return json.loads(subprocess.run(["tailscale", "status", "--json"],
                                         capture_output=True, text=True, timeout=5).stdout)
    except Exception:
        return {}


def main(argv):
    status = tailscale_status()
    if argv[1:] == ["--peers"]:
        print("\n".join(sorted(online_peers(status))))
        return 0

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from inventory_parser import parse_inventory

    with open(os.environ.get("DOTFILES_INVENTORY", INVENTORY)) as f:
        text = f.read()
    all_hosts, vps = parse_inventory(text)
    names = tailnet_names(text)
    try:
        with open("/etc/dotfiles-machine") as f:
            me = f.read().strip().lower()
    except OSError:
        me = os.uname().nodename.lower()
    # Retired VPSes must never be applied to.
    all_hosts -= vps | {me, os.uname().nodename.lower()}
    peers = online_peers(status)
    print(" ".join(sorted(h for h in all_hosts if names.get(h, h) in peers)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
