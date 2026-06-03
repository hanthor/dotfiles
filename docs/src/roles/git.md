# git

**Tags:** `dotfiles`, `git`  
**Secrets needed:** No  
**Runs on:** All machines

Deploys Git configuration with SSH commit signing.

## What It Does

1. Deploys `~/.gitconfig` with name, email, and signing preferences
2. Configures SSH commit signing using `~/.ssh/id_ed25519`
3. Deploys `~/.ssh/allowed_signers` for signature verification
4. Deploys GitHub CLI config at `~/.config/gh/config.yml`

## Key Settings

- **Signing:** SSH (`ssh-ed25519` key) for all commits
- **Allowed signers:** All fleet machine keys from Bitwarden
- **Delta:** Git diff viewer (`git-delta`) for side-by-side diffs
