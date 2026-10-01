#!/usr/bin/env python3
"""Register a new machine in inventory.yml and create its host_vars file."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory_parser import UnknownGroupError, register_host

name = sys.argv[1]
mtype = sys.argv[2] if len(sys.argv) > 2 else "desktop"
inv_path = sys.argv[3] if len(sys.argv) > 3 else "inventory.yml"

try:
    added = register_host(name, mtype, inv_path)
except UnknownGroupError:
    print(f"  Unknown machine type/group '{mtype}' in {inv_path} (e.g. desktop, server, vps)", file=sys.stderr)
    sys.exit(1)

if added:
    print(f"  Added {name} to {mtype} group in {inv_path}")
else:
    print(f"  {name} is already in inventory.")
