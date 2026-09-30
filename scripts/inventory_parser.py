#!/usr/bin/env python3
"""Shared inventory.yml mutation helpers for the machine register/purge scripts.

These edit `inventory.yml` as text on purpose: the file carries comments that
document why hosts exist (Talos nodes, the Termux/AVF split, KubeVirt port
forwards), and a YAML round-trip would drop them.
"""

import os
import re


class UnknownGroupError(ValueError):
    """Raised when a machine type has no matching group in the inventory."""


def _read(inv_path: str) -> str:
    with open(inv_path, "r", encoding="utf-8") as f:
        return f.read()


def _write(inv_path: str, content: str) -> None:
    with open(inv_path, "w", encoding="utf-8") as f:
        f.write(content)


def parse_inventory(text: str):
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


def register_host(name: str, mtype: str = "desktop", inv_path: str = "inventory.yml") -> bool:
    """Add `name` to all.hosts and to the `mtype` group.

    Returns False (writing nothing) when the host is already present. Raises
    UnknownGroupError, again writing nothing, when `mtype` names no group.
    """
    content = _read(inv_path)

    if f"    {name}:" in content:
        return False

    group_marker = f"    {mtype}:\n      hosts:\n"
    if group_marker not in content:
        raise UnknownGroupError(mtype)

    host_entry = f"    {name}:\n      ansible_host: localhost\n      ansible_connection: local\n"
    content = content.replace("all:\n  hosts:\n", f"all:\n  hosts:\n{host_entry}", 1)
    content = content.replace(group_marker, f"{group_marker}        {name}:\n", 1)

    _write(inv_path, content)
    return True


def purge_host(name: str, inv_path: str = "inventory.yml") -> bool:
    """Remove `name` from all.hosts, every group's hosts list, and its host_vars.

    Returns False (writing nothing) when the name is not a host. Group names
    share the 4-space indent of host keys, so the host-block removal is confined
    to the `all.hosts:` section — otherwise purging e.g. `vps` would delete the
    whole group and silently un-exclude the retired VPSes from apply-all.
    """
    content = _read(inv_path)

    hosts_part, sep, children_part = content.partition("\n  children:\n")

    # `    <name>:\n` plus its exactly-6-space indented children.
    host_block = re.compile(rf"^    {re.escape(name)}:\n(?:      (?! )[^\n]+\n)*", re.MULTILINE)
    hosts_part, host_removed = host_block.subn("", hosts_part, count=1)
    content = hosts_part + sep + children_part

    # The bare reference under any group's `hosts:` list.
    group_ref = re.compile(rf"^        {re.escape(name)}:\s*\n", re.MULTILINE)
    content, group_removed = group_ref.subn("", content)

    if not host_removed and not group_removed:
        return False

    _write(inv_path, content)

    hostvars = os.path.join(os.path.dirname(inv_path) or ".", "host_vars", f"{name}.yml")
    if os.path.exists(hostvars):
        os.remove(hostvars)

    return True
