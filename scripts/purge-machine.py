#!/usr/bin/env python3
"""Remove a machine from inventory.yml + its host_vars file.

Mirror of register-machine.py. Does NOT touch Bitwarden — the SSH key item
named `james@<name>` is left intact so you can re-onboard the same name later.
"""
import os, re, sys

name = sys.argv[1]
inv_path = sys.argv[2] if len(sys.argv) > 2 else "inventory.yml"

content = open(inv_path).read()
original = content

# Remove the host block under `all.hosts:` — `    <name>:\n` plus its 6-space
# indented children (ansible_host, ansible_connection, ...).
host_block = re.compile(rf"^    {re.escape(name)}:\n(?:      [^\n]+\n)*", re.MULTILINE)
content, host_removed = host_block.subn("", content, count=1)

# Remove the bare reference under any group's `hosts:` list.
group_ref = re.compile(rf"^        {re.escape(name)}:\s*\n", re.MULTILINE)
content, group_removed = group_ref.subn("", content)

if not host_removed and not group_removed:
    print(f"  {name} not found in {inv_path}")
    sys.exit(1)

open(inv_path, "w").write(content)
print(f"  Removed {name} from {inv_path}"
      f" (host_block={bool(host_removed)}, group_refs={group_removed})")

hostvars = os.path.join(os.path.dirname(inv_path) or ".", "host_vars", f"{name}.yml")
if os.path.exists(hostvars):
    os.remove(hostvars)
    print(f"  Deleted {hostvars}")
