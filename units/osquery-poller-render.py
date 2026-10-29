#!/usr/bin/env python3
"""Render the osquery poller's secret-free inventory and systemd service."""
import json
from pathlib import Path
import sys


from osquery_native_inventory import load_inventory
GROUPS = ("vps", "test_fleet", "termux_hosts")


def inventory(path):
    effective = load_inventory(path)
    hosts = effective["_meta"]["hostvars"]
    def members(name):
        group = effective.get(name, {})
        result = set(group.get("hosts", []))
        for child in group.get("children", []):
            result.update(members(child))
        return result
    groups = {name: {"hosts": {host: {} for host in sorted(members(name))}}
              for name in GROUPS}
    return {"all": {"hosts": hosts, "children": groups}}


def service(template, user, group, home, path, state):
    replacements = {
        "{{ ansible_facts['user_id'] }}": user,
        "{{ ansible_facts['user_gid'] }}": group,
        "{{ ansible_facts['env']['HOME'] }}": home,
        "{{ osquery_poller_path }}": path,
        "{{ osquery_poller_state_dir }}": state,
    }
    if any(any(c in value for c in '\n\r"\\') for value in replacements.values()):
        raise ValueError("unsupported characters in poller service values")
    text = Path(template).read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    if "{{" in text or "{%" in text:
        raise ValueError("unexpanded poller template")
    return text


def main():
    try:
        if sys.argv[1] == "inventory" and len(sys.argv) == 3:
            print(json.dumps(inventory(sys.argv[2]), indent=2, sort_keys=True))
        elif sys.argv[1] == "service" and len(sys.argv) == 8:
            print(service(*sys.argv[2:]), end="")
        else:
            raise ValueError("invalid arguments")
    except (OSError, KeyError, TypeError, ValueError):
        print("osquery poller rendering failed; verify inventory tooling and input", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
