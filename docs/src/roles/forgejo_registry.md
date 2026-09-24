# forgejo_registry

**Tags:** `secrets`, `forgejo`, `registry`  
**Secrets needed:** Yes (Login item named after the registry host)  
**Runs on:** All machines except `machine_profile: vm-test` (unless `skip_forgejo: true`)

Logs podman in to the private Forgejo container registry.

## What It Does

When `bw_unlocked` and `podman` is on `PATH`:

1. Checks `podman login --get-login {{ forgejo_registry }}` — skips if already logged in
2. Fetches `bw get username` / `bw get password` for the item named `{{ forgejo_registry }}`
3. Runs `podman login … --password-stdin`
4. Warns if the Bitwarden item is missing

## Configuration

```yaml
# roles/forgejo_registry/defaults/main.yml
forgejo_registry: forgejo.manatee-basking.ts.net
```

The Bitwarden Login item's name must equal this value; its password is a registry/package token.

## Notes

- Forgejo runs on the home Talos cluster, which is currently powered down — a fresh `podman login` can't succeed until it returns. Hosts already logged in skip the step.
