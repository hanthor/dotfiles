# shell_fonts

**Unit:** `fonts` (`units/fonts.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `shell`, `fonts`  
**Secrets needed:** No  
**Runs on:** All machines (the font install only on desktops)

Installs the [JetBrains Mono Nerd Font](https://github.com/ryanoasis/nerd-fonts) for terminals and the prompt.

## Steps

1. `font directory`: `~/.local/share/fonts/` (every host).
2. On desktops, if `JetBrainsMono/JetBrainsMonoNerdFont-Regular.ttf` is missing: download the latest `JetBrainsMono.zip` into a temporary directory, extract it there, and copy it into `~/.local/share/fonts/JetBrainsMono/`. Other font files are preserved. Run `fc-cache -f` after installation; a cache failure fails the unit and is retried on the next apply without downloading again.

## Notes

- Idempotent on the presence of the Regular `.ttf`; delete it to force a re-download. Failed extraction cannot leave that file as a false success marker; a pending cache refresh is recorded in `~/.local/share/fonts/.dotfiles-jetbrainsmono-cache-pending` until it succeeds.
- Desktop means: `DOTFILES_IS_DESKTOP`, else `is_desktop` in `host_vars`, else membership of the `desktop` group in `inventory.yml`. An invalid override or unreadable inventory fails the unit rather than reporting a non-desktop skip.
- The `gnome` unit sets Ptyxis to `JetBrainsMono Nerd Font 12`, which depends on this.
