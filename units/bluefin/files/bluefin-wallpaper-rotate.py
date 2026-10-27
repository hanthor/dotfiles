#!/usr/bin/env python3
import datetime
import subprocess
import os

def set_wallpaper():
    month = datetime.datetime.now().strftime("%m")
    # Bluefin wallpapers are named 01-bluefin.xml, 02-bluefin.xml, etc.
    wallpaper_name = f"{month}-bluefin.xml"
    local_path = os.path.expanduser(f"~/.local/share/backgrounds/bluefin/{wallpaper_name}")
    
    if not os.path.exists(local_path):
        print(f"Wallpaper {local_path} not found, skipping rotation.")
        return

    uri = f"file://{local_path}"
    print(f"Rotating wallpaper to {uri}")
    
    # Set both light and dark variants
    subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri', uri])
    subprocess.run(['gsettings', 'set', 'org.gnome.desktop.background', 'picture-uri-dark', uri])

if __name__ == "__main__":
    set_wallpaper()
