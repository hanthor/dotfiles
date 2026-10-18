# sshd

**Tags:** `system`, `sshd`  
**Secrets needed:** No  
**Runs on:** All machines

Configures the SSH daemon to accept Bitwarden environment variables from
clients that explicitly use SSH environment forwarding. The current
`just apply-remote` recipe does not depend on this drop-in: it resolves the
session on the target and exports it inside the remote command.

## What It Does

Drops a config file at `/etc/ssh/sshd_config.d/99-bw-env.conf`:

```
AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET
```

This drop-in is compatibility for explicit `SendEnv`/`AcceptEnv` workflows. It
is not required by `just apply-remote`, which uses target-side resolution
instead of SSH environment forwarding.

## Handlers

- **Reload sshd** — restarts the SSH service after config changes

## Notes

- Only runs if `/etc/ssh/sshd_config.d/` exists (Debian/Ubuntu/Fedora convention)
- On Alpine/musl systems this directory may not exist — the role skips gracefully
