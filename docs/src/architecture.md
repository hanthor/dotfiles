# Architecture

## Repository Layout

```
dotfiles/
├── site.yml              # Main playbook — entrypoint for all machines
├── inventory.yml         # Host inventory + group definitions
├── Justfile              # Task runner (just apply, just lint, etc.)
├── aws/                  # OpenTofu for the TunaOS AWS account and cluster
├── group_vars/
│   ├── all.yml           # Shared vars: packages, flatpaks, fleet config
│   └── vps.yml           # VPS-specific overrides
├── host_vars/
│   └── <machine>.yml     # Per-machine settings (is_laptop, skip_*, etc.)
├── roles/
│   └── <role>/           # Each role: tasks/, files/, templates/, vars/
├── docs/                 # This handbook
├── scripts/              # Utility scripts (inventory scan, BW seed)
├── talos-k8s/            # Talos Linux + Kubernetes cluster manifests
└── tools/                # Standalone tools, including the secret-broker
```

## How It Works

Each machine manages **itself** via `ansible-playbook --connection=local`. There's no central control node. This is an [Ansible](https://www.ansible.com/) pull model — the playbook lives on every machine and each host applies it locally.

### Local Apply

```bash
just apply
```

Runs the playbook locally with `--connection=local`. The playbook auto-detects which host it's running on by matching `/etc/dotfiles-machine` or falling back to `localhost`.

### Remote Apply

```bash
just apply-remote himachal
```

SSHes to the target, forwards the Bitwarden session token, pulls the latest dotfiles, then runs `just apply` locally on the remote machine.

### Tagged Apply

```bash
just apply-tags kube,shell
```

Runs roles and units selected by the given tags. Explicit secret-bearing tags first resolve and sync Bitwarden; unrelated tags do not prompt. `just apply-nosecrets` passes `--skip-tags secrets` to Ansible and `--no-secrets` to units (see [Bitwarden](bitwarden.md)).

#### Available Tags

Every role in `site.yml` carries one or more tags. Tags fall into two kinds: **phase tags** shared by roles in that phase, and **role tags** naming (or further scoping) one specific role. Phases follow the `# Phase N` comments in `site.yml`.

| Phase | Role | Tags |
|-------|------|------|
| (pre/post tasks) | fact setup, platform detection, secrets summary | `always` — runs on every tagged apply unless `--skip-tags always` |
| (before Phase 1) | `sudo` | `system`, `sudo` |
| System + packages | `sshd` | `system`, `sshd` |
| System + packages | `apk_packages` | `system`, `packages`, `apk` |
| System + packages | `homebrew` | `packages`, `homebrew` |
| System + packages | `termux_packages` | `system`, `packages`, `termux` |
| System + packages | `bitwarden` | `secrets`, `bitwarden` |
| System + packages | `omp` unit | `dotfiles`, `omp` |
| System + packages | `hive_ops` | `hive`, `hive_ops` |
| Secrets + auth | `ssh_keys` | `secrets`, `ssh`, `ssh_keys` |
| Secrets + auth | `ssh_mesh` | `ssh`, `mesh_check` |
| Secrets + auth | `tailscale` | `secrets`, `tailscale` |
| Desktop apps | `flatpak` | `packages`, `desktop`, `flatpak` |
| Desktop apps | `bluefin_common` | `desktop`, `bluefin` |
| Desktop apps | `gnome` | `desktop`, `gnome` |
| Desktop apps | `zen_browser` | `desktop`, `browser`, `zen_browser` |
| Desktop apps | `pipewire_audio` | `desktop`, `audio`, `pipewire` |
| Services | `syncthing` | `services`, `syncthing` |
| Services | `systemd` | `services`, `systemd` |
| Services | `bst_dashboard` | `services`, `bst_dashboard` |
| Services | `kirocrew` | `services`, `kirocrew` |
| Services | `proxy` | `services`, `proxy`, `caddy` |
| Services | `tailscale_cert` | `services`, `tailscale_cert` |
| Services | `retired_services` | `system`, `retired_services` |
| Services | `server_hardening` | `system`, `hardening`, `security` |
| Services | `fleet_facts` | `facts`, `fleet_facts` |

Shell, git, neovim and atuin config, fonts, omp, the shell/atuin/GitHub/Forgejo secrets and the kubeconfigs are not roles: they are [units](units.md) (`chezmoi`, `fonts`, `omp`, `atuin`, `shell-ai`, `github`, `kube`, `forgejo-registry`) that `just apply*` runs after the playbook. The old tags `dotfiles`, `shell`, `fonts`, `git`, `neovim`, `editor`, `atuin`, `ai`, `secrets`, `github`, `kube`, `forgejo`, `registry`, `omp` still select them through `scripts/run-units.sh`.

Common phase-wide selections:

- `--tags secrets` — every BW-backed role only (`bitwarden`, `ssh_keys`, `tailscale`; the `atuin`, `shell-ai`, `github`, `kube` and `forgejo-registry` units also run for this tag)
- `--tags desktop` — every desktop-app role (`flatpak`, `bluefin_common`, `gnome`, `zen_browser`, `pipewire_audio`)
- `--tags services` — every long-running service role (`syncthing`, `systemd`, `bst_dashboard`, `kirocrew`, `proxy`, `tailscale_cert`)
- `--skip-tags secrets` — everything except BW-backed roles. `just apply-nosecrets`, bootstrap's first phase and `phone-apply.service` also pass `--no-secrets` to units.

Tags do not replace the [`skip_*` host_vars flags](#skip-flags) or inventory-group gating described below — a role can be tag-selected and still no-op if its `when:` condition (group membership, `skip_*`, `machine_profile`) evaluates false.

## Role Structure

Each role follows the standard Ansible layout:

```
roles/<name>/
├── tasks/
│   └── main.yml         # Role entrypoint
├── files/               # Static files to deploy
├── templates/           # Jinja2 templates (with .j2 extension)
├── vars/                # Role-specific variables
│   └── main.yml
└── handlers/            # Role handlers (notify targets)
    └── main.yml
```

## Conditional Execution

Roles are gated by:

- **Inventory groups** — `when: is_desktop | bool` runs only on desktop group members
- **Host vars** — `skip_*: true` flags in `host_vars/<machine>.yml` skip specific roles
- **Tags** — `--tags kube,shell` limits which roles execute

### Skip Flags

Every flag `site.yml` reads, all defaulting to `false` (`| default(false)`). Set `skip_<name>: true` in `host_vars/<machine>.yml` to skip that role on that machine. No role reads a `skip_*` variable itself — the gating is all in `site.yml`.

| Flag | Role skipped | Other `when:` gates on the role | Set in `host_vars/` |
|------|--------------|---------------------------------|---------------------|
| `skip_sudo` | `sudo` | — | `termux` |
| `skip_ssh_mesh` | `ssh_mesh` | not `vm-test` | — |
| `skip_kube` | `kube` unit | desktop, not `vm-test` | `mumbai`, `termux` |
| `skip_forgejo` | `forgejo-registry` unit | not `vm-test` | — |
| `skip_flatpak` | `flatpak` | desktop, not `vm-test` | `mumbai`, `termux` |
| `skip_bluefin` | `bluefin_common` | desktop, not `vm-test` | `mumbai`, `termux` |
| `skip_gnome` | `gnome` | desktop, not `vm-test` | `mumbai`, `termux` |
| `skip_zen_browser` | `zen_browser` | desktop, not `vm-test` | `mumbai`, `termux` |
| `skip_pipewire_audio` | `pipewire_audio` | desktop, not `vm-test` | `mumbai` |
| `skip_syncthing` | `syncthing` | not `vps`, not `vm-test` | `mumbai`, `termux` |
| `skip_systemd` | `systemd` | — | `termux` |
| `skip_proxy` | `proxy` | not `vps`, not `vm-test` | `mumbai`, `punjab`, `termux` |
| `skip_tailscale_cert` | `tailscale_cert` | not `vps`, not `vm-test` | `mumbai`, `termux` |

"desktop" is `is_desktop` (membership of the `desktop` group unless overridden); "not `vm-test`" is `machine_profile != 'vm-test'`. Roles without a flag either always run or are gated another way: `termux_packages` (`termux_hosts` group), `kirocrew` (`kirocrew_enabled: true`), `server_hardening` (`server`/`vps` groups), `retired_services` (not `vps`, not Termux, systemd hosts). The `omp` unit skips Termux.

## Secrets Flow

1. Ansible requests a Bitwarden session (env var, cached file, or interactive unlock)
2. The `bitwarden` role resolves `BW_SESSION` and caches it
3. Secrets-tagged roles consume the session token for API calls
4. For remote applies, `scripts/bw-resolve.sh remote <host>` unlocks the vault on the target and SSH forwards that session using `SendEnv=BW_SESSION`; the target must accept it — see [Remote Apply](bitwarden.md#remote-apply).

No secrets are stored in git — the repo is fully public.
