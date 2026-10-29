# kube

**Tags:** `secrets`, `kube`
**Secrets needed:** Yes
**Runs on:** Desktop group only (unless `skip_kube: true`)

Pulls kube + Talos configs from BW for the home cluster (Bihar + Karnataka — powered down, expected back) and the historical [AWS cluster](../servers/aws-k8s/cluster.md), terminated 2026-10-25. Neither cluster is currently reachable.

## What it does

When `secrets_available` is true:

1. Ensures `~/.kube/` and `~/.talos/` exist (mode 0700).
2. `bw get notes kubeconfig` → writes to `~/.kube/config` (0600). Skipped if BW returns empty.
3. `bw get notes talosconfig` → writes to `~/.talos/config` (0600). Skipped if BW returns empty.
4. Pins `tls-server-name` on every cluster in `~/.kube/config` to `kube_tls_server_name` (default: bihar's LAN address) — the home API-server cert lacks the tailnet address in its SANs.
5. Emits a one-line warning if either home-cluster note is missing in BW.
6. `bw get notes kubeconfig-aws-migration` → `~/.kube/config-aws-migration` and `bw get notes talosconfig-aws-migration` → `~/.talos/config-aws-migration` (0600, each skipped if empty). These historical AWS files remain separate from the home configs.

When the vault is locked the role no-ops cleanly — existing local configs are preserved.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl` returns `Unable to connect to the server` after onboarding | Vault was locked, configs never deployed | Unlock BW, re-run `just apply-tags kube` |
| Warning: `kubeconfig missing in BW` | Vault was never seeded | Run `just seed-kube` from a host that already has a working config |
| Configs deployed but auth fails | Cluster PKI rotated — local configs are stale | Re-run `just seed-kube` from a healthy host, then re-apply on consumers |
| Role skipped silently on a server host that should have it | `skip_kube: true` in `host_vars/<host>.yml`, or host not in `desktop` group | Adjust inventory or host_vars |

## Seeding BW

```bash
# From a machine that already has working configs:
just seed-kube
```

This packages `~/.kube/config` and `~/.talos/config` into BW notes named `kubeconfig` and `talosconfig`. It does **not** seed the historical `*-aws-migration` notes. After seeding, every desktop's next `dots-apply` (or `just apply-tags kube`) pulls the home configs down.

## How to verify

Both commands below require the home cluster to be powered on; they fail while
it remains in storage. The former AWS cluster cannot be queried.

```bash
kubectl get nodes               # home cluster: bihar + karnataka (fails while it's powered down)
talosctl --talosconfig ~/.talos/config get members
```

## Notes

- These files contain cluster PKI material; the repo's `.gitignore` excludes the cluster source files, and these caches live in `~/` only — never commit.
- The role is gated by `is_desktop | bool and not skip_kube`. Servers don't get a kubeconfig — the cluster nodes themselves are Talos and not in the inventory.
