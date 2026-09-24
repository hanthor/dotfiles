# shell_fonts

**Tags:** `dotfiles`, `shell`, `fonts`  
**Secrets needed:** No  
**Runs on:** All machines (font install only when `is_desktop`)

Installs the [JetBrains Mono Nerd Font](https://github.com/ryanoasis/nerd-fonts) for terminals and the prompt.

## What It Does

1. Ensures `~/.local/share/fonts/` exists (every host)
2. On desktops, if `JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf` is missing:
   downloads the latest `JetBrainsMono.zip` release, unpacks it into
   `~/.local/share/fonts/JetBrainsMono/`, and runs `fc-cache -f`

## Notes

- Idempotent on the presence of the Regular `.ttf` — delete it to force a re-download
- The `gnome` role sets Ptyxis to `JetBrainsMono Nerd Font 12`, which depends on this
