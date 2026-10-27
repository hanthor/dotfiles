# sshd

**Tags:** `system`, `sshd`  
**Secrets needed:** No  
**Runs on:** All machines

Configures the SSH daemon to accept Bitwarden environment variables. `just apply-remote` resolves the session on the target and forwards it back using `SendEnv=BW_SESSION` without putting it in the remote command line.

## What It Does

Drops a config file at `/etc/ssh/sshd_config.d/99-bw-env.conf`:

```
AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET
```

The drop-in is required for session-bearing remote applies; those applies fail if the target rejects `BW_SESSION`.

## Handlers

- **Reload sshd** — restarts the SSH service after config changes

## Notes

- Only runs if `/etc/ssh/sshd_config.d/` exists (Debian/Ubuntu/Fedora convention)
- On Alpine/musl systems this directory may not exist — the role skips gracefully
