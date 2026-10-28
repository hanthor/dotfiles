# forgejo_registry

**Unit:** `forgejo-registry` (`units/forgejo-registry.sh`; see [Units](../units.md))  
**Tags:** `secrets`, `forgejo`, `registry`  
**Secrets needed:** Yes (login item named after the registry host)  
**Runs on:** All machines except `machine_profile: vm-test` or `skip_forgejo: true` in `host_vars`

Logs podman in to the private Forgejo container registry.

## What it does

1. `SKIPPED:` unless `podman` is installed; no-op when `podman login --get-login <registry>` already succeeds.
2. With an unlocked vault: `bw get username` / `bw get password` for the item named after the registry, then `podman login <registry> -u <user> --password-stdin`. The username is trimmed at its edges, preserving internal whitespace. A missing, empty, or failed credential read prints `PARTIAL:` and is not a failure; partial output from a failed read is never used.

## Configuration

The registry host is `FORGEJO_REGISTRY` in `units/forgejo-registry.sh` (default `forgejo.manatee-basking.ts.net`, overridable from the environment). The Bitwarden login item's name must equal it; its password is a registry/package token.

## Notes

- Forgejo ran on the home cluster, which is powered down, so a fresh `podman login` cannot succeed until it returns. Hosts already logged in skip the step.
