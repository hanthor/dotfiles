# Architecture

## Repository layout

- `Justfile` provides local and remote fleet commands.
- `scripts/run-units.sh` selects and orders native units; `mise.toml` registers them as tasks.
- `units/*.sh` and their helpers/assets configure the host. `home/` is the chezmoi source for shell, Git, Neovim and Atuin configuration.
- `inventory.yml`, `group_vars/` and `host_vars/` hold fleet membership and settings. Some connection keys retain their historical `ansible_` names and are read by native tooling.
- `scripts/` holds operational and Bitwarden helpers. `roles/pi/files/skills/` remains a source of omp skills; not every directory named `roles` is an active Ansible role.
- `aws/` contains OpenTofu for the TunaOS AWS account; `talos-k8s/` contains home-cluster manifests; `docs/` is the handbook.

## Applying configuration

`just apply` pulls the checkout, resolves and syncs a Bitwarden session when available, and invokes the units runner. If the vault is unavailable, the apply continues with secrets disabled. `just apply-nosecrets` also invokes the runner with `--no-secrets`; it does not unlock the vault. Neither invokes an Ansible playbook.

`just apply-tags kube,shell` selects units through the tag map in `scripts/run-units.sh`. Secret-bearing tags attempt to resolve and sync Bitwarden; on failure the selected units still run with secrets disabled, and the recipe returns an error. Tags select units, not a bypass of their platform, inventory, profile or host-variable gates. See [Units](units.md) for staging and failure behavior.

`just apply-remote HOST` resolves the session on the target, forwards it over SSH using `SendEnv=BW_SESSION`, pulls the remote checkout and runs `just apply` there. The target SSH daemon must accept the forwarded variable. Phone updates use a separate user timer and a temporary archive, with secrets disabled.

`just check` sets `UNITS_CHECK=1` for the native runner. Check coverage and exact safety/accuracy across platforms are still subject to integration verification; do not treat it as a complete substitute for a reviewed apply or a guarantee of no changes.

### Available tags

The authoritative mapping is `tasks_for_tag` in `scripts/run-units.sh`. Common selections include `system`, `packages`, `dotfiles`, `shell`, `ssh`, `mesh_check`, `secrets`, `desktop`, `services`, `osquery`, `security`, `hive`, and `fleet_facts`, plus individual names such as `omp`, `tailscale`, `gnome`, and `proxy`. A tag selects only the listed units: unselected prerequisites are not implicitly applied. `--no-secrets` suppresses unit vault access, rather than removing all secret-capable units from the selection.

## Conditional execution

Each unit implements its own gates. Depending on the unit these include inventory groups, `skip_*` host variables, `machine_profile`, platform detection, executable availability, or noninteractive root access. For example, SSH mesh skips `skip_ssh_mesh` and `vm-test`; proxy and Tailscale certificates skip VPSes and `vm-test`; package units detect their respective platforms. Consult the unit and its [reference page](roles/) before applying. Machine identity comes from `DOTFILES_MACHINE`, `/etc/dotfiles-machine`, or hostname, in that order.

The retired `matrix` and `telengana` VPSes remain powered on for burn-in: **do not restart anything on them**. The shared unit library skips both identities before unit work, including package upgrades that could restart services indirectly. This guard does not authorize other changes to those hosts.

## Secrets

The repository is public. Unit helpers read a usable `BW_SESSION` or `/tmp/bw_session`, without prompting, and honor `UNITS_NO_SECRETS=1`. Apply recipes resolve and sync sessions before starting secret-bearing work. Individual units decide how to handle missing items or a locked vault, generally reporting `PARTIAL` or `SKIPPED` and retaining existing secret files. See [Bitwarden](bitwarden.md) and each unit's documentation for details. Remote session forwarding requires a properly configured SSH server.
