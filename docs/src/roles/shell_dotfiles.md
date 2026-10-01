# shell_dotfiles

**Tags:** `dotfiles`, `shell`  
**Secrets needed:** No  
**Runs on:** All machines

Deploys the shell, prompt, multiplexer and terminal configs.

## What It Does

1. `~/.config/shell/aliases.sh` (bash/zsh) and `~/.config/fish/conf.d/aliases.fish` — shared aliases, templated
2. `~/.bashrc`, `~/.zshrc`, `~/.zprofile` — templated
3. `~/.config/fish/config.fish`, `~/.tmux.conf`, `~/.inputrc`, `~/.config/starship.toml` — copied as-is
4. Ghostty terminfo: ships `xterm-ghostty.terminfo` and compiles it into
   `~/.terminfo` with `tic`, so SSH sessions from Ghostty don't break
   ncurses apps. Warns and skips if `tic` isn't installed.
5. `~/.config/ghostty/config` — auto light/dark following GNOME (inert on headless hosts)

## Fleet aliases

| Alias | Expands to |
|-------|-----------|
| `dots` | `cd ~/.local/share/dotfiles && just apply-nosecrets` (git pull + `--skip-tags secrets`) |
| `dots-apply` | `cd ~/.local/share/dotfiles && git pull --ff-only && just apply` (full, with BW unlock) |
| `dots-edit` | open the repo in `$EDITOR` |

In fish these are abbreviations (`abbr`), not aliases.

## Notes

- Shell secrets (`~/.config/shell/secrets.sh`, `~/.config/fish/conf.d/secrets.fish`) are written by [`shell_ai`](shell_ai.md), not here
- Source files: `roles/shell_dotfiles/files/` and `roles/shell_dotfiles/templates/`
