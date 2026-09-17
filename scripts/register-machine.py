#!/usr/bin/env python3
"""Register a new machine in inventory.yml and create its host_vars file."""
import sys
from inventory_parser import register_host

name = sys.argv[1]
mtype = sys.argv[2] if len(sys.argv) > 2 else "desktop"
inv_path = sys.argv[3] if len(sys.argv) > 3 else "inventory.yml"

if register_host(name, mtype, inv_path):
    print(f"  Added {name} to {mtype} group in {inv_path}")
else:
    print(f"  {name} is already in inventory.")
