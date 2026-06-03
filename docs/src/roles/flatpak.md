# flatpak

**Tags:** `packages`, `desktop`, `flatpak`  
**Secrets needed:** No  
**Runs on:** Desktop group only (`skip_flatpak: false`)

Installs and manages [Flatpak](https://flatpak.org/) applications from [Flathub](https://flathub.org/).

## What It Does

1. Fixes broken Flatpak symlinks if present
2. Adds the Flathub remote
3. Removes unwanted system flatpaks (Firefox, Thunderbird — replaced by Zen)
4. Installs missing flatpaks in batch (fast path), falling back to individual installs
5. Updates all flatpaks when `upgrade: true` is set
6. Creates Chromium wrapper scripts for CLI compatibility

## Package List

Defined in `group_vars/all.yml` as `system_flatpaks`. Key apps:

| App | Flatpak ID |
|-----|-----------|
| Zen Browser | `app.zen_browser.zen` |
| VS Code | `com.visualstudio.code` |
| Ungoogled Chromium | `com.github.Eloston.UngoogledChromium` |
| Easy Effects | `com.github.wwmm.easyeffects` |
| Flatseal | `com.github.tchx84.Flatseal` |
| GNOME apps | Calculator, Calendar, Clocks, Contacts, Loupe, etc. |
| Vesktop | `dev.vencord.Vesktop` |
| Obsidian | `md.obsidian.Obsidian` |

## Wrapper Scripts

Creates `~/.local/bin/chromium`, `~/.local/bin/google-chrome`, and `~/.local/bin/chromium-browser` that exec into the Ungoogled Chromium flatpak — tools that hardcode `google-chrome` or `chromium-browser` still work.

## Notes

- Installs system-wide (`--system`) with `become: true`
- Batch install tolerates partial failures — individual retries catch stragglers
