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

def validate_host_name(name: str) -> None:
    """Require a single DNS hostname, safe in inventory, paths and SSH."""
    if len(name) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", name):
        raise ValueError("machine name must be a lowercase DNS hostname")


def host_groups(text: str, host: str):
    """Return direct children groups containing a host in this inventory layout."""
    groups, section, group, in_hosts = set(), None, None, False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        match = re.match(r"([A-Za-z0-9_-]+):(?:\s*(?:\{\})?)?(?:\s*#.*)?$", line.strip())
        if not match:
            continue
        key = match.group(1)
        if indent == 2:
            section, group, in_hosts = key, None, False
        elif section == "children" and indent == 4:
            group, in_hosts = key, False
        elif section == "children" and indent == 6:
            in_hosts = key == "hosts"
        elif section == "children" and indent == 8 and in_hosts and key == host:
            groups.add(group)
    return groups


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
            match = re.match(r"([A-Za-z0-9_-]+):(?:\s*(?:\{\})?)?(?:\s*#.*)?$", line.strip())
            if match:
                all_hosts.add(match.group(1))
        elif indent == 4 and section == "children":
            group = key
        elif indent == 8 and section == "children" and group == "vps":
            vps.add(key)
    return all_hosts, vps


def parse_host_vars(text: str):
    """{host: {var: value}} for the 6-space `key: value` lines under each all.hosts entry.

    Values are stripped of inline comments and quotes; no PyYAML (see parse_inventory).
    """
    hosts, section, host = {}, None, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 2:
            section = line.strip().rstrip(":")
        elif indent == 4 and section == "hosts":
            host = line.strip().rstrip(":")
            hosts[host] = {}
        elif indent == 6 and section == "hosts" and host is not None:
            m = re.match(r"([A-Za-z0-9_]+):\s*(.*?)\s*(?:#.*)?$", line.strip())
            if m and m.group(2):
                hosts[host][m.group(1)] = m.group(2).strip("'\"")
    return hosts


def set_host_var(text: str, host: str, key: str, value):
    """Return `text` with `host`'s `key` set to `value` (or removed when value is None).

    Edits only the host's own block under all.hosts, keeping its inline comment.
    A missing key is appended after the block's last variable line. Unknown hosts
    leave the text unchanged.
    """
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.startswith("  children:"):
            break
        if re.fullmatch(rf"    {re.escape(host)}:\s*(#.*)?", line):
            start = i
            break
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and (lines[end].startswith("      ") or not lines[end].strip() or lines[end].lstrip().startswith("#")):
        if lines[end].startswith("    ") and not lines[end].startswith("      "):
            break
        end += 1
    last_var = start
    for i in range(start + 1, end):
        if lines[i].startswith("      ") and not lines[i].lstrip().startswith("#"):
            last_var = i
            m = re.match(rf"(      {re.escape(key)}:\s*)([^#\n]*?)(\s*(?:#.*)?)$", lines[i])
            if m:
                if value is None:
                    del lines[i]
                else:
                    lines[i] = f"{m.group(1)}{value}{m.group(3) if m.group(3).strip() else ''}"
                return "\n".join(lines)
    if value is not None:
        lines.insert(last_var + 1, f"      {key}: {value}")
    return "\n".join(lines)


def register_host(name: str, mtype: str = "desktop", inv_path: str = "inventory.yml") -> bool:
    """Add `name` to all.hosts and to the `mtype` group.

    Returns False (writing nothing) when the host is already present. Raises
    UnknownGroupError, again writing nothing, when `mtype` names no group.
    """
    validate_host_name(name)
    content = _read(inv_path)

    if name in parse_inventory(content)[0]:
        return False

    group_marker = f"    {mtype}:\n      hosts:\n"
    if group_marker not in content:
        raise UnknownGroupError(mtype)
    if "all:\n  hosts:\n" not in content:
        raise ValueError("inventory has no supported all.hosts section")

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

    # `    <name>:` plus its exactly-6-space indented children. Any of those
    # lines can end the section with no newline: partition() consumed the one
    # before `children:`, and the file itself need not end in one.
    host_block = re.compile(rf"^    {re.escape(name)}:[ \t]*(?:\n|\Z)(?:      (?! )[^\n]+(?:\n|\Z))*", re.MULTILINE)
    hosts_part, host_removed = host_block.subn("", hosts_part, count=1)
    if sep and host_removed:
        # Removing the last block leaves the previous line's newline behind;
        # sep supplies it again.
        hosts_part = hosts_part.rstrip("\n")
    content = hosts_part + sep + children_part

    # The bare reference under any group's `hosts:` list, which may be the
    # file's last line.
    group_ref = re.compile(rf"^        {re.escape(name)}:[ \t]*(?:\n|\Z)", re.MULTILINE)
    content, group_removed = group_ref.subn("", content)

    if not host_removed and not group_removed:
        return False

    _write(inv_path, content)

    hostvars = os.path.join(os.path.dirname(inv_path) or ".", "host_vars", f"{name}.yml")
    if os.path.exists(hostvars):
        os.remove(hostvars)

    return True
