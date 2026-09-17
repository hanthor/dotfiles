#!/usr/bin/env python3
"""Centralized helper module for parsing and modifying inventory.yml safely."""

import os
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None


def load_inventory_data(inv_path: str = "inventory.yml") -> dict:
    """Load inventory structure as data, using PyYAML if available."""
    if not os.path.exists(inv_path):
        return {}
    if yaml is not None:
        try:
            with open(inv_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            pass

    # Basic fallback extraction if PyYAML is not installed
    content = open(inv_path, "r", encoding="utf-8").read()
    all_hosts = set(re.findall(r"^\s{4}(\w[\w-]*):\s*$", content, re.MULTILINE))
    group_hosts = {}
    current_group = None
    for line in content.splitlines():
        g_match = re.match(r"^\s{4}(\w[\w-]*):\s*$", line)
        if g_match:
            current_group = g_match.group(1)
            group_hosts.setdefault(current_group, [])
            continue
        h_match = re.match(r"^\s{8}(\w[\w-]*):\s*$", line)
        if h_match and current_group:
            group_hosts[current_group].append(h_match.group(1))

    return {"all": {"hosts": {h: {} for h in all_hosts}}, "groups": group_hosts}


def get_all_hostnames(inv_path: str = "inventory.yml") -> list:
    """Return sorted list of all host names in inventory."""
    data = load_inventory_data(inv_path)
    if "all" in data and "hosts" in data["all"] and isinstance(data["all"]["hosts"], dict):
        return sorted(list(data["all"]["hosts"].keys()))
    
    # Fallback to regex scan
    content = open(inv_path, "r", encoding="utf-8").read()
    hosts = set(re.findall(r"^\s{4}(\w[\w-]*):\s*$", content, re.MULTILINE))
    return sorted(list(hosts))


def get_non_vps_hosts(inv_path: str = "inventory.yml", exclude_self: bool = True) -> list:
    """Return sorted list of online/manageable non-VPS hosts from inventory."""
    hosts = get_all_hostnames(inv_path)
    content = open(inv_path, "r", encoding="utf-8").read()
    vps = set(re.findall(r"^\s{6}(\w[\w-]*):\s*$", content, re.MULTILINE))
    
    exclude = set(vps)
    if exclude_self:
        exclude.add(os.uname().nodename.lower())

    return sorted([h for h in hosts if h not in exclude])


def register_host(name: str, mtype: str = "desktop", inv_path: str = "inventory.yml") -> bool:
    """Register a new host under all.hosts and target group, preserving formatting."""
    content = open(inv_path, "r", encoding="utf-8").read()
    if f"    {name}:" in content:
        return False

    host_entry = f"    {name}:\n      ansible_host: localhost\n      ansible_connection: local\n"
    content = content.replace("all:\n  hosts:\n", f"all:\n  hosts:\n{host_entry}", 1)

    group_marker = f"    {mtype}:\n      hosts:\n"
    if group_marker in content:
        content = content.replace(group_marker, f"{group_marker}        {name}:\n", 1)

    with open(inv_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def purge_host(name: str, inv_path: str = "inventory.yml") -> bool:
    """Remove host from all.hosts, group references, and host_vars file."""
    content = open(inv_path, "r", encoding="utf-8").read()

    host_block = re.compile(rf"^    {re.escape(name)}:\n(?:      [^\n]+\n)*", re.MULTILINE)
    content, host_removed = host_block.subn("", content, count=1)

    group_ref = re.compile(rf"^        {re.escape(name)}:\s*\n", re.MULTILINE)
    content, group_removed = group_ref.subn("", content)

    if not host_removed and not group_removed:
        return False

    with open(inv_path, "w", encoding="utf-8") as f:
        f.write(content)

    hostvars = os.path.join(os.path.dirname(inv_path) or ".", "host_vars", f"{name}.yml")
    if os.path.exists(hostvars):
        os.remove(hostvars)

    return True


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "non_vps":
        inv = sys.argv[2] if len(sys.argv) > 2 else "inventory.yml"
        print(" ".join(get_non_vps_hosts(inv)))
    elif len(sys.argv) > 1 and sys.argv[1] == "all_hosts":
        inv = sys.argv[2] if len(sys.argv) > 2 else "inventory.yml"
        print(" ".join(get_all_hostnames(inv)))
