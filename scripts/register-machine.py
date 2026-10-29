#!/usr/bin/env python3
"""Register a machine or check its reviewed inventory membership."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory_parser import UnknownGroupError, host_groups, parse_inventory, register_host, validate_host_name


def main(argv):
    check = bool(argv and argv[0] == "--check")
    if check:
        argv = argv[1:]
    if not 1 <= len(argv) <= 3:
        print("usage: register-machine.py [--check] NAME [TYPE] [INVENTORY]", file=sys.stderr)
        return 2
    name = argv[0]
    mtype = argv[1] if len(argv) > 1 else "desktop"
    inv_path = argv[2] if len(argv) > 2 else "inventory.yml"
    try:
        validate_host_name(name)
        if check:
            if mtype not in ("desktop", "server", "vps", "termux_hosts"):
                raise ValueError("machine type must be desktop, server, vps, or termux_hosts")
            with open(inv_path, encoding="utf-8") as source:
                content = source.read()
            if name not in parse_inventory(content)[0]:
                return 3
            groups = host_groups(content, name)
            if mtype not in groups:
                raise ValueError(f"{name} is not in the {mtype} group")
            return 0
        added = register_host(name, mtype, inv_path)
    except (OSError, UnknownGroupError, ValueError) as error:
        print(f"registration failed: {error}", file=sys.stderr)
        return 2
    if added:
        print(f"  Added {name} to {mtype} group in {inv_path}")
    else:
        print(f"  {name} is already in inventory.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
