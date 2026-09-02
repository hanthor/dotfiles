# kube

**Tags:** `secrets`, `kube`
**Secrets needed:** Yes
**Runs on:** Desktop group only (unless `skip_kube: true`)

Pulls `kubeconfig` + `talosconfig` from Bitwarden so any desktop in the fleet can talk to both the **AWS Talos cluster** (active workloads: Matrix, Hive) and the **metal Talos cluster** (Bihar + Karnataka, currently offline in storage).

## What it does

When `bw_unlocked` is true:

1. Ensures `~/.kube/` and `~/.talos/` exist (mode 0700).
2. Fetches `kubeconfig` and `talosconfig` (metal cluster).
3. Fetches `kubeconfig-aws-migration` and `talosconfig-aws-migration` (AWS cluster).
4. Sets the TLS server name pinning (`192.168.0.5`) on the metal cluster so tailnet connections verify against the SAN.
5. Automatically merges both cluster definitions into **`~/.kube/config`** (with contexts `admin@talos-k8s` and `admin@aws-migration`) and **`~/.talos/config`** (with contexts `talos-k8s` and `aws-migration`).
6. Preserves standalone copies in `~/.kube/config-aws-migration` and `~/.talos/config-aws-migration` for backward compatibility.

## Multi-Cluster Context Switching

With the unified configuration, you can seamlessly switch contexts on any fleet desktop:

```bash
# View contexts
kubectl config get-contexts
talosctl config contexts

# Switch active context
kubectl config use-context admin@aws-migration
talosctl config context aws-migration

# Or target per-command
kubectl --context=admin@aws-migration get pods -A
talosctl --context=aws-migration get members
```

## Seeding Bitwarden

```bash
# From a machine with working configs:
just seed-kube
```

This packages all configs (`kubeconfig`, `talosconfig`, `kubeconfig-aws-migration`, `talosconfig-aws-migration`) into Bitwarden notes. Other fleet desktops will pull and merge them on `just apply-tags kube` or `just update`.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl` returns `Unable to connect to the server` after onboarding | Vault was locked, configs never deployed | Unlock BW, re-run `just apply-tags kube` |
| Metal cluster (`admin@talos-k8s`) connection timeout | Bihar + Karnataka are currently powered off in storage | Switch context to `admin@aws-migration` |
| AWS cluster (`admin@aws-migration`) connection timeout | Security group allowlist went stale or needs Tailscale routing | Authorize current client IP on SG `migration-admin-bootstrap` |
| Warning: `kubeconfig missing in BW` | Vault was never seeded | Run `just seed-kube` from a host that has valid configs |

## Notes

- All credential files contain cluster PKI materials and are gitignored.
- Gated by `is_desktop | bool and not skip_kube`.
