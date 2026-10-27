# kube

**Unit:** `kube` (`units/kube.sh`; see [Units](../units.md))  
**Tags:** `secrets`, `kube`  
**Secrets needed:** Yes  
**Runs on:** Desktops only (`SKIPPED:` otherwise, or with `skip_kube: true` / `machine_profile: vm-test` in `host_vars`)

Pulls kube + Talos configs from Bitwarden for the home cluster (Bihar + Karnataka — powered down, expected back) and the historical [AWS cluster](../servers/aws-k8s/cluster.md), terminated 2026-10-25. Neither cluster is currently reachable; the AWS configs are retained separately.

## Steps

With an unlocked vault (a locked vault or `--no-secrets` prints `SKIPPED:` and leaves existing files alone):

1. `kube dirs`: `~/.kube/` and `~/.talos/` (0700).
2. `home kubeconfig`: `bw get notes kubeconfig` → `~/.kube/config` (0600).
3. `home talosconfig`: `bw get notes talosconfig` → `~/.talos/config` (0600).
4. `pin tls-server-name`: after writing the home kubeconfig, every cluster in it gets `--tls-server-name=$KUBE_TLS_SERVER_NAME` (`units/kube.conf`, default bihar's LAN address `192.168.0.5`): the home API-server cert lacks the tailnet address in its SANs. If `kubectl` is missing, the unit warns and skips the pin.
5. `aws kubeconfig` / `aws talosconfig`: `kubeconfig-aws-migration` → `~/.kube/config-aws-migration`, `talosconfig-aws-migration` → `~/.talos/config-aws-migration` (0600). These historical files remain separate from the home configs and no longer access the terminated cluster.

A missing or empty note prints `warn:` and leaves its existing file untouched.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl` returns `Unable to connect to the server` | The home cluster is powered down, or the vault was locked and configs were never deployed | Home-cluster connectivity returns only after it is powered on; if configs are missing, unlock BW and re-run `just apply-tags kube` |
| `warn: kubeconfig ... missing in BW` | The note is unavailable or empty | Check the vault; if it needs seeding, run `just seed-kube` from a host with the intended home configs |
| Configs deployed but auth fails when the home cluster is running | Cluster PKI may have rotated — local configs are stale | Re-run `just seed-kube` from a healthy host, then re-apply on consumers |
| Unit prints `SKIPPED: not a desktop` on a host that should have it | `skip_kube: true` in `host_vars/<host>.yml`, or host not in the `desktop` group | Adjust inventory or host_vars |

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
- The unit is gated by desktop membership and `skip_kube` / `machine_profile: vm-test`. Servers don't get a kubeconfig; the Talos cluster nodes are not in the inventory.
