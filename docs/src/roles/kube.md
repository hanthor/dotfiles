# kube

**Tags:** `secrets`, `kube`  
**Secrets needed:** Yes  
**Runs on:** Desktop group only (`skip_kube: false`)

Deploys [Kubernetes](https://kubernetes.io/) and [Talos](https://www.talos.dev/) cluster configuration from Bitwarden.

## What It Does

1. Fetches `kubeconfig` from Bitwarden (secure note) → writes to `~/.kube/config` (mode 0600)
2. Fetches `talosconfig` from Bitwarden (secure note) → writes to `~/.talos/config` (mode 0600)

## Seeding Bitwarden

```bash
# From any machine with working cluster configs:
just seed-kube
```

This uploads both config files to Bitwarden. After seeding, other desktop machines can pull them with `just apply-tags kube`.

## Notes

- Missing items produce a warning, not a failure
- Skip on a host with `skip_kube: true` in its `host_vars`
- Both files contain cluster PKI material — never commit to git
