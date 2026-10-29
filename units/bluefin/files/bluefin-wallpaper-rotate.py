#!/usr/bin/env python3
import datetime
from pathlib import Path
import subprocess
import sys

SYSTEM_BACKGROUNDS = Path('/usr/share/backgrounds/bluefin')

def set_wallpaper():
    month = datetime.datetime.now().strftime("%m")
    # Bluefin wallpapers are named 01-bluefin.xml, 02-bluefin.xml, etc.
    wallpaper_name = f"{month}-bluefin.xml"
    local_path = Path.home() / '.local/share/backgrounds/bluefin' / wallpaper_name
    if not local_path.exists():
        local_path = SYSTEM_BACKGROUNDS / wallpaper_name

    if not local_path.exists():
        print(f"Wallpaper {local_path} not found, skipping rotation.")
        return 0

    uri = local_path.as_uri()
    print(f"Rotating wallpaper to {uri}")

    # Attempt both variants, but report a failure if either could not be set.
    failed = False
    for key in ('picture-uri', 'picture-uri-dark'):
        result = subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', key, uri])
        failed |= result.returncode != 0
    return int(failed)

if __name__ == "__main__":
    sys.exit(set_wallpaper())
