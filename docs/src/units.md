# Units

A **unit** is an idempotent bash script in `units/` that configures one independent piece of a machine. Units exist because Ansible aborts a whole role when one task fails: on himachal the `omp` role died at `Deploy omp-kiro-provider config` (`~/.config/omp` did not exist), so the routing merge, `omp-route` and the auth-broker config never ran. In a unit, a failing step is recorded and the next independent step still runs; independent units run in parallel.

[mise](https://mise.jdx.dev) is the runner: each unit is a `mise.toml` task, and `mise run` supplies the dependency graph, parallel jobs and `--continue-on-error`.

Everything not listed under `units/` is still an Ansible role.

## Running units

| Command | What it does |
|---|---|
| `just units` | Run every unit in parallel (`just units --tags omp`, `--no-secrets` also accepted) |
| `mise run units` | Same, straight through mise |
| `mise run unit:omp` | One unit |
| `mise run --dry-run units` | Show what would run |
| `mise tasks deps units` | Show the task graph |
| `just apply`, `apply-nosecrets`, `apply-tags`, `dotfiles` | Run Ansible first, then `scripts/run-units.sh` (never skipped because Ansible failed; exit codes are combined) |

`scripts/run-units.sh [--no-secrets] [--tags a,b]` is the one wrapper the recipes call. It maps Ansible tags to units (`tasks_for_tag`, mirroring the tags of the roles the units replaced), runs the selection with `mise run --continue-on-error --jobs 8 --output prefix --timeout 15m`, and exits with mise's status. Without `mise` on `PATH` it prints `mise not installed; running units sequentially` and runs the selected units one after another, continuing after failures, so hosts without mise (Termux, musl) keep updating.

## Rules for a unit

- Idempotent bash. `set -uo pipefail`, never `set -e`.
- Source `units/lib.sh`: `step "desc" cmd...` (a failure marks the unit failed and continues), `soft "desc" cmd...` (a failure is only a warning), `note "..."`, `finish` (exit 1 only if a `step` failed), `install_if_changed src dest mode`, `bw_session` (a usable Bitwarden session or nothing; never prompts; honours `UNITS_NO_SECRETS=1`).
- mise treats any non-zero exit as failure, so "skipped" and "partial" are printed as `SKIPPED: ...` / `PARTIAL: ...` lines with exit 0.
- Never echo a secret or put one on a command line.

## Adding a unit

1. Create `units/<name>.sh` (executable) with a `# shellcheck source=units/lib.sh` line above its `. lib.sh` line.
2. Add `[tasks."unit:<name>"]` with `file = "units/<name>.sh"` to `mise.toml`.
3. Add `<name>` to `ALL_UNITS` and to the right `tasks_for_tag` branches in `scripts/run-units.sh`.

`tests/test_units_registry.py` fails if the three places disagree.

`units/`, `mise.toml` and `scripts/run-units.sh` are executed by the fleet timer, so they are intentionally not carved out of CODEOWNERS.

## chezmoi

File-based config (shell, git, neovim, atuin config) is managed by [chezmoi](https://www.chezmoi.io/) from `home/` (`.chezmoiroot` contains `home`, so `.chezmoi.toml.tmpl`, `.chezmoidata.yaml` and `.chezmoiscripts/` live there). `unit:chezmoi` runs `chezmoi --source <repo> --keep-going --force --no-tty apply --init`: `--keep-going` continues past a failing file or script, `--force` overwrites like the old roles did, `--no-tty` avoids a TTY, and `--init` regenerates the config from `home/.chezmoi.toml.tmpl`.

**Back up and review existing dotfiles before the first apply.** The current `--force` will overwrite local edits to managed targets without prompting on every apply. First adoption can replace an existing target even without `--force`: chezmoi does not treat a pre-existing, never-written target as a conflict by default. Review the intended changes with `chezmoi --source <repo> diff` (after initializing the config with the correct machine data), and keep a private backup of any local files you need. A safer future cutover should detect both first-adoption and later local conflicts and fail closed for unattended runs, with interactive review; merely removing `--force` does not protect initial adoption.

If chezmoi is absent the unit fails rather than reporting a successful skip. Homebrew hosts can run `just packages`, Termux users can run `pkg install chezmoi`, and Alpine/postmarketOS users can enable the community repository and run `sudo apk add chezmoi`.

- Data: `machine`, `is_desktop` (true when the host is in the `desktop` group of `inventory.yml`), `user_name`, `user_email`, `alias_groups`.
- Secrets are **not** chezmoi templates: the `bitwarden` template function aborts a whole template on a missing item. The `shell-ai` and `atuin` units handle secrets.
- chezmoi never deletes files it does not manage (no `exact_` directories).
- `ssh_keys` stays an Ansible role (key lifecycle, `authorized_keys` merge).
