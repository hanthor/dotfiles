#!/usr/bin/env python3
"""Resolve proxy and certificate settings with inventory group precedence."""
import json
import sys

from osquery_native_inventory import group_contains, load_inventory


def main(mode, inventory_path, machine):
    if mode not in ("proxy", "cert"):
        raise ValueError("invalid service inventory query")
    # Check membership before loading settings or doing anything to the host.
    inventory = load_inventory(inventory_path, resolve_vars=False)
    if machine not in inventory["_meta"]["hostvars"]:
        raise ValueError("machine is absent from inventory")
    if group_contains(inventory, "vps", machine):
        print("skip")
        return
    flag = "skip_proxy" if mode == "proxy" else "skip_tailscale_cert"
    field = "web_services" if mode == "proxy" else "tailscale_domain"
    inventory = load_inventory(inventory_path, fields=(flag, "machine_profile", field))
    values = inventory["_meta"]["hostvars"][machine]
    skipped = values.get(flag, False)
    profile = values.get("machine_profile", "")
    if not isinstance(skipped, bool) or not isinstance(profile, str):
        raise ValueError("invalid service exclusion setting")
    if skipped or profile == "vm-test":
        print("skip")
        return
    value = values.get(field, [] if mode == "proxy" else "")
    if mode == "proxy" and value is None:
        value = []
    if mode == "cert" and not isinstance(value, str):
        raise ValueError("invalid Tailscale certificate domain")
    print("run")
    print(json.dumps(value, separators=(",", ":")) if mode == "proxy" else value)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 4:
            raise ValueError("invalid service inventory query")
        main(*sys.argv[1:])
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"service inventory: {error}", file=sys.stderr)
        sys.exit(1)
