#!/usr/bin/env python3
"""Register a new machine in inventory.yml and create its host_vars file."""
import sys, re

name = sys.argv[1]
mtype = sys.argv[2] if len(sys.argv) > 2 else "desktop"
inv_path = sys.argv[3] if len(sys.argv) > 3 else "inventory.yml"

content = open(inv_path).read()

if f"    {name}:" in content:
    print(f"  {name} is already in inventory.")
    sys.exit(0)

host_entry = f"    {name}:\n      ansible_host: localhost\n      ansible_connection: local\n"
content = content.replace("all:\n  hosts:\n", f"all:\n  hosts:\n{host_entry}", 1)

group_marker = f"    {mtype}:\n      hosts:\n"
if group_marker in content:
    content = content.replace(group_marker, f"{group_marker}        {name}:\n", 1)

open(inv_path, "w").write(content)
print(f"  Added {name} to {mtype} group in {inv_path}")
