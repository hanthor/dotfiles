# kube

**Unit:** `kube` (`units/kube.sh`; see [Units](../units.md))  
**Tags:** `secrets`, `kube`  
**Secrets needed:** Yes  
**Runs on:** Desktops only (`SKIPPED:` otherwise, or with `skip_kube: true` / `machine_profile: vm-test` in `host_vars`)

Pulls the kube + Talos configs for both clusters from Bitwarden so any desktop in the fleet can talk to them: the home cluster (Bihar + Karnataka, powered down, expected back) and the [AWS cluster](../servers/aws-k8s/cluster.md) (its nodes were terminated on 2026-10-25; the configs are kept).

## Steps

With an unlocked vault (a locked vault or `--no-secrets` prints `SKIPPED:` and leaves existing files alone):

1. `kube dirs`: `~/.kube/` and `~/.talos/` (0700).
2. `home kubeconfig`: `bw get notes kubeconfig` → `~/.kube/config` (0600). A missing note prints `warn:` and leaves the file as it is.
3. `home talosconfig`: `bw get notes talosconfig` → `~/.talos/config` (0600).
4. `pin tls-server-name`: after writing the home kubeconfig, every cluster in it gets `--tls-server-name=$KUBE_TLS_SERVER_NAME` (`units/kube.conf`, default bihar's LAN address `192.168.0.5`): the home API-server cert lacks the tailnet address in its SANs.
5. `aws kubeconfig` / `aws talosconfig`: `kubeconfig-aws-migration` → `~/.kube/config-aws-migration`, `talosconfig-aws-migration` → `~/.talos/config-aws-migration`. Separate files keep both clusters independently usable.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl` returns `Unable to connect to the server` after onboarding | Vault was locked, configs never deployed | Unlock BW, re-run `just apply-tags kube` |
| `warn: kubeconfig ... missing in BW` | Vault was never seeded | Run `just seed-kube` from a host that already has a working config |
| Configs deployed but auth fails | Cluster PKI rotated — local configs are stale | Re-run `just seed-kube` from a healthy host, then re-apply on consumers |
| Unit prints `SKIPPED: not a desktop` on a host that should have it | `skip_kube: true` in `host_vars/<host>.yml`, or host not in the `desktop` group | Adjust inventory or host_vars |

## Seeding BW

```bash
# From a machine that already has working configs:
just seed-kube
```

This packages `~/.kube/config` and `~/.talos/config` into BW notes named `kubeconfig` and `talosconfig`. It does **not** seed the `*-aws-migration` notes — update those by hand. After seeding, every desktop's next `dots-apply` (or `just apply-tags kube`) pulls them down.

## How to verify

```bash
kubectl get nodes               # home cluster: bihar + karnataka (fails while it's powered down)
talosctl --talosconfig ~/.talos/config get members
KUBECONFIG=~/.kube/config-aws-migration kubectl get nodes   # AWS cluster
```

## Notes

- Both files contain cluster PKI material; the repo's `.gitignore` excludes the cluster source files, and these caches live in `~/` only — never commit.
- Gated by desktop membership and `skip_kube`. Servers don't get a kubeconfig; the cluster nodes are not in the inventory.
