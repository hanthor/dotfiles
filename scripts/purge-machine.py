#!/usr/bin/env python3
"""Remove a machine from inventory.yml + its host_vars file.

Mirror of register-machine.py. Does NOT touch Bitwarden — the SSH key item
named `james@<name>` is left intact so you can re-onboard the same name later.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventory_parser import purge_host

name = sys.argv[1]
inv_path = sys.argv[2] if len(sys.argv) > 2 else "inventory.yml"

if purge_host(name, inv_path):
    print(f"  Removed {name} from {inv_path}")
else:
    print(f"  {name} not found in {inv_path}")
    sys.exit(1)
