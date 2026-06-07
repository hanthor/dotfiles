# kube

**Tags:** `secrets`, `kube`
**Secrets needed:** Yes
**Runs on:** Desktop group only (unless `skip_kube: true`)

Pulls `kubeconfig` + `talosconfig` from BW so any desktop in the fleet can talk to the Talos cluster (Bihar + Karnataka).

## What it does

When `bw_unlocked` is true:

1. Ensures `~/.kube/` and `~/.talos/` exist (mode 0700).
2. `bw get notes kubeconfig` → writes to `~/.kube/config` (0600). Skipped if BW returns empty.
3. `bw get notes talosconfig` → writes to `~/.talos/config` (0600). Skipped if BW returns empty.
4. Emits a one-line warning if either note is missing in BW.

When the vault is locked the role no-ops cleanly — existing local configs are preserved.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl` returns `Unable to connect to the server` after onboarding | Vault was locked, configs never deployed | Unlock BW, re-run `just apply-tags kube` |
| Warning: `kubeconfig missing in BW` | Vault was never seeded | Run `just seed-kube` from a host that already has a working config |
| Configs deployed but auth fails | Cluster PKI rotated — local configs are stale | Re-run `just seed-kube` from a healthy host, then re-apply on consumers |
| Role skipped silently on an LLM/server host that should have it | `skip_kube: true` in `host_vars/<host>.yml`, or host not in `desktop` group | Adjust inventory or host_vars |

## Seeding BW

```bash
# From a machine that already has working configs:
just seed-kube
```

This packages `~/.kube/config` and `~/.talos/config` into BW notes named `kubeconfig` and `talosconfig`. After seeding, every desktop's next `dots-apply` (or `just apply-tags kube`) pulls them down.

## How to verify

```bash
kubectl get nodes               # should list bihar + karnataka
talosctl --talosconfig ~/.talos/config get members
```

## Notes

- Both files contain cluster PKI material; the repo's `.gitignore` excludes the cluster source files, and these caches live in `~/` only — never commit.
- The role is gated by `is_desktop | bool and not skip_kube`. Servers don't get a kubeconfig because they're either *in* the cluster (`bihar`, `karnataka`) or have no business talking to it.
