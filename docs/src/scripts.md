# Utility Scripts

`scripts/` contains helpers used locally, by remote applies, user services and CI. The native fleet entrypoint is `scripts/run-units.sh`; unit implementations and their assets live in `units/`.

## Applying and status

- `scripts/run-units.sh [--no-secrets] [--tags a,b]` selects units from its tag map, orders prerequisites in stages, and runs independent selections through mise or a sequential fallback. It continues after independent failures; selected dependents may be skipped if a prerequisite fails. `just units` invokes this wrapper.
- `just apply`, `just apply-nosecrets` and `just apply-tags <tags>` invoke the wrapper. The first pulls and resolves Bitwarden, the second disables secret access, and tagged applies resolve Bitwarden only for secret-bearing selections. See [Units](units.md).
- `just check` requests unit inspection with `UNITS_CHECK=1`. Coverage and safety across platforms are subject to integration verification; do not assume a complete or universally non-mutating dry run.
- `scripts/record-apply.py EXIT_CODE [LABEL [SKIP_TAGS]]` records the recipe result, timestamp and git revision in `~/.cache/dotfiles/last-apply.json`. `scripts/last-apply-status.py` reads it for `just doctor` and returns nonzero for failed, stale or unreadable records. A successful record can still include partial or skipped units.

The shared unit library skips retired `matrix` and `telengana` before unit work. **Nothing on those VPSes may be restarted**; pre-run operations and other scripts are not covered by that guard.

## Inventory

- `scripts/register-machine.py <name> [type] [inventory-path]` adds an inventory host and group membership; `--check` verifies existing membership without writing. `just onboard` proposes the change and a host-vars file in an isolated worktree, opens a PR, and prints bootstrap instructions to use after review and merge.
- `scripts/purge-machine.py <name> [inventory-path]` removes inventory and host variables, not Bitwarden items. `just purge` wraps it.
- `scripts/online_hosts.py` intersects online Tailscale peers with inventory, excluding VPSes and the local host. `--peers` prints online peer names instead; the SSH mesh unit uses it. Tailscale status failure yields no peers.
- `scripts/nmap-inventory.sh [CIDR]` scans the LAN and cross-references Tailscale; it requires nmap and network access. `just inventory` provides the usual entrypoint.

## Bitwarden helpers

- `scripts/bw-resolve.sh local` prints a shell export for a usable local session; use `eval "$(scripts/bw-resolve.sh local)"` to set it. It tries the existing session, cache and interactive unlock. `remote <host>` attempts to unlock on that host and prints its session token; the apply recipes forward it with SSH `SendEnv=BW_SESSION`.
- `scripts/bw-unlock.sh` resolves a local session and prints the raw token. Avoid exposing token output. Sessions are not guaranteed portable between hosts.
- `scripts/bw-seed-kube.sh` upserts the `kubeconfig` and `talosconfig` secure notes from local files, then syncs. `KUBECONFIG` and `TALOSCONFIG` can override the default paths. These credentials contain cluster PKI; do not commit them.
- `scripts/bw-seed-omp-broker.sh` seeds the omp broker token. See the [omp reference](roles/omp.md).
- `scripts/bw-seed-ssh-keys.sh` is a legacy helper with a hardcoded machine list. It reads private and public keys locally or over SSH, writes SSH-key items and may register GitHub keys, then writes a chezmoi `dot_ssh/authorized_keys` source file. Remote host keys must already be verified and trusted. Review its hardcoded hosts and destination before use; it does not use the native fleet unit's vault item naming or managed-block merge. The normal key lifecycle is documented in [ssh_keys](roles/ssh_keys.md).

## Other helpers

- `scripts/sync-brews.sh` compares Homebrew's dumped formulae with `core_brews` and `desktop_brews` in `group_vars/all.yml` and adds missing formulae to `desktop_brews`; review its changes before committing.
- `scripts/kubevirt-node up|down|status` historically managed an AWS KubeVirt instance and VMs, using `~/.kube/config-aws-migration` by default. The AWS Talos cluster was terminated; do not treat these commands as a home-cluster runbook or use them without checking the current AWS state. The home Talos cluster is separately offline in storage, not decommissioned.
- `scripts/ess-render-values.py` reads sensitive ESS Helm values on stdin and writes transformed values to stdout for the former AWS cluster. It does not retrieve the vault item itself or configure the standalone OCI deployment. Do not write secret-bearing output to a tracked file.
- `scripts/osquery-fleet.py` collects private fleet monitoring reports; see [fleet facts and osquery](roles/fleet_facts.md).
