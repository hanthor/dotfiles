# sshd

**Tags:** `system`, `sshd`  
**Secrets needed:** No  
**Runs on:** All machines

Configures the SSH daemon to accept forwarded Bitwarden environment variables.

## What It Does

Drops a config file at `/etc/ssh/sshd_config.d/99-bw-env.conf`:

```
AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET
```

This is required for `just apply-remote` — it forwards your local Bitwarden session token over SSH so the remote machine can access secrets without its own unlock.

## Handlers

- **Reload sshd** — restarts the SSH service after config changes

## Notes

- Only runs if `/etc/ssh/sshd_config.d/` exists (Debian/Ubuntu/Fedora convention)
- On Alpine/musl systems this directory may not exist — the role skips gracefully
