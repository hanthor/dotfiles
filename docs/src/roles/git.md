# git

**Unit:** `chezmoi` (`units/chezmoi.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `git`  
**Secrets needed:** No  
**Runs on:** All machines with `chezmoi` installed

Git configuration with SSH commit signing, as chezmoi-managed files under `home/`:

| Target | Source |
|---|---|
| `~/.gitconfig` | `dot_gitconfig.tmpl` (data: `user_name`, `user_email`, `.chezmoi.homeDir`) |
| `~/.gitignore_global`, `~/.gitmessage` | `dot_gitignore_global`, `dot_gitmessage` |
| `~/.config/gh/config.yml` | `dot_config/gh/config.yml` |

## Key Settings

- **Signing:** SSH (`ssh-ed25519` key) for all commits
- **Allowed signers:** `~/.ssh/allowed_signers` is written by the `ssh_keys` role from the fleet machine keys in Bitwarden
- **Delta:** Git diff viewer (`git-delta`) for side-by-side diffs
