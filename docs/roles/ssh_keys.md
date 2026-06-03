# ssh_keys

**Tags:** `secrets`, `ssh`, `ssh_keys`  
**Secrets needed:** Yes  
**Runs on:** All machines

Manages per-machine ed25519 SSH keys, cross-machine authorized_keys, and allowed_signers for git commit verification.

## What It Does

### Key Management

For each machine (`james@<hostname>` in Bitwarden):

1. **Key exists in BW** → writes it to `~/.ssh/id_ed25519`
2. **Key on disk but not in BW** → stores it in BW as an SSH Key object
3. **Neither** → generates a new ed25519 key pair → stores in BW

### Cross-Machine Trust

- Fetches all other machines' public keys from Bitwarden
- Builds `~/.ssh/authorized_keys` with every fleet key
- Updates `~/.ssh/allowed_signers` for git commit signing verification

## Notes

- Every machine can SSH to every other machine without password prompts
- The `github` role registers the same ssh key with GitHub
