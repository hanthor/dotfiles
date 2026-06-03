# zen_browser

**Tags:** `desktop`, `browser`, `zen_browser`  
**Secrets needed:** No  
**Runs on:** Desktop group only

Configures Zen Browser (Firefox-based) as the default browser.

## What It Does

1. Pins Zen Browser to the GNOME dock
2. Removes Firefox and Thunderbird from the dock if present
3. Sets Zen as the default web browser

## Notes

- Zen is installed via Flatpak (`app.zen_browser.zen`)
- Firefox and Thunderbird are intentionally removed from the dock — Zen replaces both
