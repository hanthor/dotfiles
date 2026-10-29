# Units

A unit is a Bash entrypoint in `units/` configuring one concern. Shared helpers in `units/lib.sh` let a unit record failed steps while continuing independent work. Native units replace the fleet playbook; their supporting scripts, templates and files are under `units/`, with chezmoi-managed files under `home/`.

## Running units

| Command | Behavior |
|---|---|
| `just apply` | Pull, resolve and sync Bitwarden when possible, and run the fleet units. |
| `just apply-nosecrets` | Run units with vault access disabled; pull failure is tolerated. |
| `just apply-tags omp,shell` | Select units mapped from tags; secret-bearing selections attempt vault resolution. |
| `just dotfiles` / `just packages` | Run the corresponding tag selection. |
| `just units --tags omp` | Run the wrapper directly; `--no-secrets` is also accepted. |
| `mise run units` | Run the same wrapper. |
| `mise run unit:omp` | Run one registered unit directly, without wrapper prerequisite ordering. |
| `just check` | Set `UNITS_CHECK=1` and run the native selection in inspection mode. Coverage and safety remain subject to integration verification; do not assume a complete or universally non-mutating dry run. |

`scripts/run-units.sh [--no-secrets] [--tags a,b]` is the authoritative tag map and registry. It runs package managers and other prerequisites in stages, then runs independent later units in parallel using mise (`UNITS_JOBS`, default 8), continuing after independent failures. Without mise, stages run sequentially. A failure in a selected SSH keys, Tailscale or Zen unit suppresses its selected dependent units; unselected prerequisites are not implicitly applied. Fleet facts runs last. `SKIPPED` and `PARTIAL` lines describe exclusions or incomplete work and are not, by themselves, proof of a complete configuration.

`just apply-tags` resolves and syncs Bitwarden for explicitly secret-bearing tags; if it fails, selected units run with secrets disabled and the recipe reports failure. The no-secrets path prevents unit vault access even when a session exists. Himachal's phone timer sends a temporary archive of the tracked checkout and runs native units with `--no-secrets` on each target independently.

The shared unit library skips identities `matrix` and `telengana` before unit work, including package transactions. These retired VPSes remain powered on for burn-in: nothing on them may be restarted. The guard does not authorize other changes to those hosts.

## Implementing a unit

Use idempotent Bash with `set -uo pipefail`, source `units/lib.sh` with a shellcheck source directive, and use `step` for recorded failures, `soft` for best-effort work, `note` for status and `finish` for the resulting exit status. `bw_session` is noninteractive and honors `UNITS_NO_SECRETS=1`; do not log secret values. Preserve user data and make platform, profile, privilege and retired-host safeguards explicit. Direct unit invocation does not provide wrapper ordering.

Register a new executable `units/<name>.sh` in `mise.toml`, `ALL_UNITS` and the relevant `tasks_for_tag` branches and stage in `scripts/run-units.sh`. Executable configuration paths are not intended to bypass CODEOWNERS review.

## chezmoi

`.chezmoiroot` points to `home/`, which contains the source files, `.chezmoi.toml.tmpl`, `.chezmoidata.yaml` and `.chezmoiscripts/`. `units/chezmoi.sh` applies shell, Git, Neovim and Atuin configuration with `--keep-going --force --no-tty apply --init`. It fails if chezmoi is unavailable (on Termux it first attempts a best-effort `pkg install`). Desktop detection honors `DOTFILES_IS_DESKTOP` or host `is_desktop`, then inventory membership. If the inventory lookup cannot be validated, including when Mike Farah `yq` is unavailable, the unit fails without applying files.

**Back up and review existing dotfiles before first apply.** `--force` overwrites local edits to managed targets without prompting, including on subsequent runs. Even without `--force`, first adoption of an existing target can replace it. The source uses no `exact_` directories, so unmanaged files are not deleted by directory synchronization. Secrets are handled by units rather than chezmoi templates, so unavailable vault items do not abort unrelated file templates. `units/ssh-keys.sh` and `units/ssh-mesh.sh` manage SSH key lifecycle and authorization separately.

## Kubernetes access

The [`kube` unit](roles/kube.md) configures Karnataka K3s on active Linux and macOS computers, including servers, the phone's Debian VM and Termux. It honors explicit `skip_kube` / `vm-test` exclusions and the retired-host guard, not desktop membership. `kubectl` comes from core Homebrew (`kubernetes-cli`), APK or Termux packages. On a fresh client use `just apply-tags packages,kube`; `just apply-tags kube` alone does not install missing prerequisites.

The separate Bitwarden note `kubeconfig-karnataka-k3s` supplies the active credentials. Applies merge the `karnataka-k3s` context into `~/.kube/config` and select it by default, preserving other contexts and retained Talos/AWS recovery material. Locked-vault and no-secrets applies leave existing configs untouched. A deliberate `KUBE_CACHED_ONLY=1` invocation can instead merge an already provisioned private cache without Bitwarden; see the [client rollout instructions](roles/kube.md#prerequisites-and-rollout).
