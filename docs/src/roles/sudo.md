# sudo

**Tags:** `system`, `sudo`  
**Secrets needed:** No  
**Runs on:** All machines

Grants passwordless sudo to the current user and cleans up old sudoers entries.

## What It Does

1. Writes a sudoers drop-in at `/etc/sudoers.d/zz-<user>` granting `NOPASSWD:ALL`
2. Validates the file with `visudo -cf` before deploying
3. Removes old/conflicting sudoers files from previous naming conventions

## Notes

- Required for unattended playbook runs — many tasks use `become: true`
- The `zz-` prefix ensures this file loads last, overriding any earlier restrictions
