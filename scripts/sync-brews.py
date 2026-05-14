import subprocess
import yaml
import os
import sys

# Load existing vars
all_vars_path = 'group_vars/all.yml'
with open(all_vars_path, 'r') as f:
    all_vars = yaml.safe_load(f)

core_brews = set(all_vars.get('core_brews', []))
desktop_brews = set(all_vars.get('desktop_brews', []))

# Get current reality
print("Fetching current Homebrew state...")
reality = subprocess.run(['/home/linuxbrew/.linuxbrew/bin/brew', 'bundle', 'list', '--formula'], 
                        capture_output=True, text=True).stdout.splitlines()
reality = set(r.strip() for r in reality if r.strip())

# Logic:
# 1. Keep core_brews as they are (all machines need them)
# 2. Add anything new to desktop_brews
# 3. (Optional) Remove things that are not in reality?
#    Let's be additive for now to avoid breaking other machines in the fleet.

new_core = []
for b in all_vars.get('core_brews', []):
    if b in reality:
        new_core.append(b)
    else:
        print(f"Keeping {b} in core (not installed here but might be elsewhere)")
        new_core.append(b)

current_known = core_brews | desktop_brews
newly_found = reality - current_known

new_desktop = list(all_vars.get('desktop_brews', []))
for nf in sorted(newly_found):
    print(f"Adding new package to desktop_brews: {nf}")
    new_desktop.append(nf)

all_vars['core_brews'] = new_core
all_vars['desktop_brews'] = new_desktop

# Write back
with open(all_vars_path, 'w') as f:
    yaml.dump(all_vars, f, sort_keys=False, default_flow_style=False)

print("Done! group_vars/all.yml updated.")
