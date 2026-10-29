# kube

**Unit:** `kube` (`units/kube.sh`; see [Units](../units.md))  
**Tags:** `secrets`, `kube`  
**Secrets needed:** Yes  
**Runs on:** Active Linux and macOS computers, including servers, the phone's Debian VM and Termux. Explicit `skip_kube: true` / `machine_profile: vm-test` exclusions still apply. Retired `matrix` and `telengana` are never modified.

[Karnataka K3s](../servers/talos-k8s/karnataka/README.md#current-k3s-cluster) is the fleet's active default cluster, reached over Tailscale at `https://100.66.158.127:6443`. The former home Talos cluster and terminated AWS cluster remain recovery material, not current workload targets. Their Bitwarden notes and local configs must not be repurposed for K3s.

## Prerequisites and rollout

`kubectl` is a core package: Homebrew `kubernetes-cli` on supported glibc Linux/macOS hosts, `kubectl` through APK on Alpine and through `pkg` on Termux. Termux also installs `@bitwarden/cli` through its existing npm package unit. Desktop inventory membership is not required.

```bash
# First apply, including missing package prerequisites:
just apply-tags packages,kube

# Subsequent credential refresh/default-context selection:
just apply-tags kube
```

An individual remote may use `just apply-remote HOST` after reviewing the other units it applies. Do not target retired hosts. Offline computers receive the configuration on their next secret-enabled apply; the no-secrets timer cannot distribute credentials.

For a production host where installing Bitwarden/Node or running the full package unit is inappropriate, install only a supported `kubectl` binary and privately provision the standalone note contents as `~/.kube/config-karnataka-k3s` (directory 0700, regular file 0600). Then, from the checkout, explicitly apply only the local cache:

```bash
KUBE_CACHED_ONLY=1 UNITS_NO_SECRETS=1 bash units/kube.sh
```

This opt-in never invokes Bitwarden or seeds recovery notes. It validates and merges the local cache, preserves the existing default's contexts and migration backup, and selects `karnataka-k3s`. A missing cache fails without changing the default. It does not refresh credentials; provision renewed cache contents privately when needed. Ordinary no-secrets/timer runs still skip without changing configs.

## Bitwarden contract

Create a distinct **secure note** named `kubeconfig-karnataka-k3s`. Its standard `notes` field must contain a complete standalone kubeconfig:

- Context, cluster and user names are all `karnataka-k3s`; `current-context` is `karnataka-k3s`.
- The server is `https://100.66.158.127:6443`, not localhost.
- Embed the cluster CA and client certificate/key, and use normal certificate verification. Do not set `insecure-skip-tls-verify`.
- Store and transform credentials only in private files or pipes. Never paste the note, client key or raw kubeconfig into logs, chat or this public repository.

The unit reads `bw get notes kubeconfig-karnataka-k3s`; it never edits vault notes. The historical `kubeconfig`, `talosconfig`, `kubeconfig-aws-migration` and `talosconfig-aws-migration` notes retain their existing meanings.

## Apply behavior

Except for the explicit cached-only mode above, a locked vault or `--no-secrets` prints `SKIPPED:` and leaves existing files alone. Otherwise:

1. Require `kubectl`, then create `~/.kube/` and `~/.talos/` with mode 0700.
2. Seed missing recovery caches only: home `kubeconfig` → `~/.kube/config-home-talos`, `talosconfig` → `~/.talos/config`, and the historical AWS notes → the matching `config-aws-migration` files in those directories. Existing recovery files are preserved, with permissions restricted to 0600. The newly seeded home kubeconfig receives the historical TLS server-name pin from `units/kube.conf` (default `192.168.0.5`), not the K3s kubeconfig.
3. Fetch K3s into a private temporary directory and select the required `karnataka-k3s` context. A failed or empty fetch may use the last successfully installed `~/.kube/config-karnataka-k3s` cache; without that cache the unit fails without changing the default config.
4. Merge K3s, the existing `~/.kube/config` and home recovery contexts into a private config, then select `karnataka-k3s`. Existing contexts take precedence over recovery-note contexts; the reserved K3s names take precedence over their older local copies. AWS recovery stays in its existing separate file.
5. On first migration of an existing default config, preserve its original bytes in `~/.kube/config-pre-karnataka-k3s` (0600). Atomically install the dedicated K3s cache and merged default config, both 0600. Subsequent applies preserve the original backup and restore K3s as the default without deleting historical or custom contexts.

Symlinks and non-regular destination files are rejected instead of overwritten. Merge/context-selection failures leave the existing default untouched. Temporary credential files are private and removed on exit; command output containing kubeconfig data is never logged.

`just check` inspects only local existence and permissions, without reading Bitwarden items or mutating files. It reports that credential/default-context comparison cannot safely be completed offline; it does not claim to have verified cluster access.

## Retained home-note seeding

`just seed-kube` now reads `~/.kube/config-home-talos` and `~/.talos/config`, not the merged default kubeconfig. It only updates the retained home notes; it does not seed K3s or historical AWS notes. For deliberate home-cluster recovery from another private source file, set `KUBECONFIG=/absolute/path/to/home-only-config` explicitly. Never seed the historical home note from the merged K3s default.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `kubectl missing; apply packages before kube` | A tag-only invocation omitted package prerequisites | Run `just apply-tags packages,kube` on the intended active client |
| Karnataka note unavailable and no cached config exists | Note missing, empty, failed read or unavailable to this account | Provision the distinct K3s note, unlock/sync the vault and reapply; do not replace historical notes |
| K3s config lacks a usable `karnataka-k3s` context | Note uses the unrenamed K3s `default` context or is malformed | Correct the standalone K3s note using the private provisioning workflow |
| Cannot merge kubeconfigs | An existing config is invalid or references unavailable credential files | Repair the private source config; its default file is left untouched on merge failure |
| `kubectl` cannot reach Karnataka | Client tailnet routing, server firewall or K3s may be unavailable | Inspect connectivity and the current server; do not run historical Talos recovery commands |
| `SKIPPED: skip_kube / vm-test` | Explicit host opt-out or test-machine profile | Review the intended host policy; changing desktop membership has no effect |

## Checking active access

Run these on the intended client after rollout; they do not print credentials:

```bash
kubectl config current-context                 # karnataka-k3s
kubectl --context karnataka-k3s get nodes
kubectl --context karnataka-k3s get pods -A
```

Historical Talos commands require a deliberately restored cluster. Do not interpret retained contexts as evidence that the old cluster is running, and do not apply historical recovery commands to repurposed Karnataka.
