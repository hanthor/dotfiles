#!/usr/bin/env python3
import os
import subprocess
import configparser
import re
import ast

def run_cmd(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

def apply_gschema_override(file_path):
    print(f"Applying gsettings from {file_path}")
    config = configparser.ConfigParser(strict=False, interpolation=None)
    # GSchema override files use [schema.id] sections
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Simple parser for gschema override format
    sections = re.split(r'\n\s*\[(.*?)\]\s*\n', '\n' + content)
    for i in range(1, len(sections), 2):
        schema = sections[i].strip()
        body = sections[i+1]
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                key = key.strip()
                val = val.strip()
                print(f"  Setting {schema} {key} = {val}")
                # Redirect system background paths to local ones
                if 'usr/share/backgrounds/bluefin' in val:
                    local_path = os.path.expanduser('~/.local/share/backgrounds/bluefin')
                    val = val.replace('/usr/share/backgrounds/bluefin', local_path)
                    print(f"    Redirected to local path: {val}")

                # Ensure Caffeine is always included in enabled-extensions
                if schema == 'org.gnome.shell' and key == 'enabled-extensions':
                    try:
                        exts = ast.literal_eval(val)
                        if 'caffeine@patapon.info' not in exts:
                            exts.append('caffeine@patapon.info')
                            val = repr(exts)
                            print(f"    Added Caffeine to enabled-extensions: {val}")
                    except Exception as e:
                        print(f"    Error patching enabled-extensions: {e}")

                res = run_cmd(['gsettings', 'set', schema, key, val])
                if res.returncode != 0:
                    print(f"    Warning: Failed to set {key}: {res.stderr.strip()}")

def apply_dconf_keyfile(file_path):
    print(f"Applying dconf from {file_path}")
    # dconf load / < file_path
    with open(file_path, 'r') as f:
        subprocess.run(['dconf', 'load', '/'], stdin=f)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: bluefin-sync.py <dir>")
        sys.exit(1)
    
    sync_dir = sys.argv[1]
    
    # 1. Apply gsettings overrides
    override_path = os.path.join(sync_dir, "zz0-bluefin-modifications.gschema.override")
    if os.path.exists(override_path):
        apply_gschema_override(override_path)
    
    # 2. Apply dconf distro.d files
    dconf_dir = os.path.join(sync_dir, "dconf")
    if os.path.exists(dconf_dir):
        for f in sorted(os.listdir(dconf_dir)):
            if f.startswith('0') and not f.endswith('locked-settings'):
                apply_dconf_keyfile(os.path.join(dconf_dir, f))
