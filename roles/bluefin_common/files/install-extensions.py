#!/usr/bin/env python3
import json, urllib.request, zipfile, io, os, subprocess

EXTENSIONS = [
    'appindicatorsupport@rgcjonas.gmail.com',
    'dash-to-dock@micxgx.gmail.com',
    'blur-my-shell@aunetx',
    'gsconnect@andyholmes.github.io',
    'logomenu@aryan_k',
    'search-light@icedman.github.com'
]

USER_EXT_DIR = os.path.expanduser('~/.local/share/gnome-shell/extensions')
os.makedirs(USER_EXT_DIR, exist_ok=True)

def install_ext(uuid):
    if os.path.exists(os.path.join(USER_EXT_DIR, uuid)):
        print(f"Extension {uuid} already installed.")
        return

    print(f"Installing {uuid}...")
    try:
        # Fetch extension metadata to find the latest version
        url = f"https://extensions.gnome.org/extension-query/?search={uuid}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            ext_data = next(e for e in data['extensions'] if e['uuid'] == uuid)
            pk = ext_data['pk']
        
        # Fetch download URL for the latest version
        url = f"https://extensions.gnome.org/extension-info/?pk={pk}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            ext_info = json.loads(response.read().decode())
            # Pick the highest version compatible with current shell
            try:
                shell_version = subprocess.run(['gnome-shell', '--version'], capture_output=True, text=True).stdout.split()[2]
                major_version = shell_version.split('.')[0]
            except:
                major_version = "47" # Fallback
            
            # Find the best version for our shell
            ver_map = ext_info['shell_version_map']
            best_ver_data = None
            if major_version in ver_map:
                best_ver_data = ver_map[major_version]
            else:
                # Fallback to any version that contains the major version in its support list
                for v in sorted(ver_map.keys(), reverse=True):
                    if major_version in v.split('.'):
                        best_ver_data = ver_map[v]
                        break
            
            if not best_ver_data:
                # Final fallback: just take the newest one
                latest_v = sorted(ver_map.keys(), reverse=True)[0]
                best_ver_data = ver_map[latest_v]

            version_pk = best_ver_data['pk']
            download_url = f"https://extensions.gnome.org/download-extension/{uuid}.shell-extension.zip?version_tag={version_pk}"
        
        # Download and install via gnome-extensions CLI to trigger Shell scan
        tmp_zip = f"/tmp/{uuid}.zip"
        req = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(tmp_zip, 'wb') as out:
            out.write(response.read())
        
        # Run gnome-extensions install
        res = subprocess.run(['gnome-extensions', 'install', '--force', tmp_zip], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"Successfully installed {uuid}")
        else:
            print(f"Failed to install {uuid} via CLI: {res.stderr.strip()}")
            # Fallback to manual extraction if CLI fails
            with zipfile.ZipFile(tmp_zip) as z:
                dest = os.path.join(USER_EXT_DIR, uuid)
                os.makedirs(dest, exist_ok=True)
                z.extractall(dest)
            print(f"Manually extracted {uuid} as fallback")
        
        if os.path.exists(tmp_zip):
            os.remove(tmp_zip)

    except Exception as e:
        print(f"Failed to install {uuid}: {e}")

if __name__ == "__main__":
    for uuid in EXTENSIONS:
        install_ext(uuid)
