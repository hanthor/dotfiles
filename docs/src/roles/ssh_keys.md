# ssh_keys

**Tags:** `secrets`, `ssh`, `ssh_keys`
**Secrets needed:** Yes
**Runs on:** All machines

Manages per-machine ed25519 SSH keys, distributes the fleet's public keys via `authorized_keys`, and maintains the `allowed_signers` list for git commit verification.

**Source of truth is the local disk.** Bitwarden is the durable mirror that lets new/rebuilt machines recover and lets the rest of the fleet stay in sync.

## What it does

For the local machine's key (`james@<hostname>` in Bitwarden):

1. **No key on disk** → fetch from BW; if absent there too, `ssh-keygen` a fresh ed25519 pair.
2. **Local pub key matches BW** → no-op.
3. **Local pub key differs from BW** → leave the Bitwarden item unchanged and warn by default. An intentional rotation must opt in with `dots-apply -e ssh_keys_force_push=true`; only then is the BW item replaced so every other host sees the current key on its next apply. This gate prevents a key generated while the vault was locked from clobbering the stored key.

Then, regardless of whether the local item changed:

- Slurps every other `james@<machine>` SSH item from BW in a single `bw list` call.
- Rewrites `~/.ssh/authorized_keys` with the union of those + `extra_authorized_keys`.
- Refreshes `~/.ssh/known_hosts` for every fleet host via `ssh-keyscan`, removing stale entries first.
- Updates `~/.ssh/allowed_signers` with this host's pub key for git commit signing.

If `bw_unlocked` is false (vault locked, BW not installed, etc.), every BW-touching step is skipped and `authorized_keys` is **not** rewritten — preserving the existing file rather than wiping it with an empty list.

## Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `Permission denied (publickey)` from a host that worked yesterday | Local key changed but BW still has the old pub key | For an intentional rotation, run `dots-apply -e ssh_keys_force_push=true` on the source host with BW unlocked, then run `dots-apply` on the failing host. If the mismatch was accidental, restore the Bitwarden key locally instead of forcing it. |
| Some hosts missing from `authorized_keys` | Those hosts never round-tripped their key to BW | Run `dots-apply` on each missing host once, with BW unlocked. |
| New ed25519 key generated on a host that should have inherited an existing key | BW item missing/empty for this hostname | Verify the BW entry name matches `james@<hostname>` exactly. |

## How to verify

```bash
# Check this host's key is in BW
bw get item "james@$(hostname)" | jq '.sshKey.publicKey' | grep -F "$(awk '{print $2}' ~/.ssh/id_ed25519.pub)"

# Check who can SSH in here
cat ~/.ssh/authorized_keys

# Test SSH to every fleet host
for h in $(yq '.all.hosts | keys | join(" ")' inventory.yml); do
  ssh -o BatchMode=yes -o ConnectTimeout=3 "$h" "echo OK" 2>&1 | head -1
done
```

## Notes

- Every machine SSHes to every other machine without password prompts after one round-trip apply.
- The same key is used for GitHub auth + commit signing (registered by the `github` role).
- The role tolerates a locked vault and never destructively rewrites `authorized_keys` when BW returned no data.
