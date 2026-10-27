# shell_fonts

**Unit:** `fonts` (`units/fonts.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `shell`, `fonts`  
**Secrets needed:** No  
**Runs on:** All machines (the font install only on desktops)

Installs the [JetBrains Mono Nerd Font](https://github.com/ryanoasis/nerd-fonts) for terminals and the prompt.

## Steps

1. `font directory`: `~/.local/share/fonts/` (every host).
2. On desktops, if `JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf` is missing: `install JetBrains Mono Nerd Font` downloads the latest `JetBrainsMono.zip` release into a temp dir, unpacks it into `~/.local/share/fonts/JetBrainsMono/`, then `font cache` (soft) runs `fc-cache -f`.

## Notes

- Idempotent on the presence of the Regular `.ttf`; delete it to force a re-download.
- Desktop means: `DOTFILES_IS_DESKTOP`, else `is_desktop` in `host_vars`, else membership of the `desktop` group in `inventory.yml`. An invalid override or unreadable inventory fails the unit rather than reporting a non-desktop skip.
- The `gnome` unit sets Ptyxis to `JetBrainsMono Nerd Font 12`, which depends on this.
