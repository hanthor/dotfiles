# github

**Tags:** `secrets`, `github`  
**Secrets needed:** Yes  
**Runs on:** All machines

Configures GitHub CLI authentication and registers the machine's SSH key with GitHub.

## What It Does

1. Refreshes `gh` CLI auth scopes
2. Registers `~/.ssh/id_ed25519` with GitHub as both:
   - An **authentication key** (git push/pull over SSH)
   - A **signing key** (verified commits)

## Notes

- Requires the `ssh_keys` role to have already run (key must exist)
- The signing key registration enables the "Verified" badge on commits
