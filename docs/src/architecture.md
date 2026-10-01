# Architecture

## Repository Layout

```
dotfiles/
├── site.yml              # Main playbook — entrypoint for all machines
├── inventory.yml         # Host inventory + group definitions
├── Justfile              # Task runner (just apply, just lint, etc.)
├── group_vars/
│   ├── all.yml           # Shared vars: packages, flatpaks, fleet config
│   └── vps.yml           # VPS-specific overrides
├── host_vars/
│   └── <machine>.yml     # Per-machine settings (is_laptop, skip_*, etc.)
├── roles/
│   └── <role>/           # Each role: tasks/, files/, templates/, vars/
├── docs/                 # This handbook
├── scripts/              # Utility scripts (inventory scan, BW seed)
└── talos-k8s/            # Talos Linux + Kubernetes cluster manifests
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

Runs only roles tagged with the given tags. Useful for deploying specific configs without running the full playbook. `--skip-tags` works the same way in reverse — `just apply-nosecrets` is `--skip-tags secrets` under the hood (see [Bitwarden](bitwarden.md)).

#### Available Tags

Every role in `site.yml` carries one or more tags. Tags fall into two kinds: **phase tags** shared by every role in that phase, and **role tags** naming (or further scoping) one specific role.

| Phase | Role | Tags |
|-------|------|------|
| Bootstrap | `sudo` | `system`, `sudo` |
| System + packages | `sshd` | `system`, `sshd` |
| System + packages | `apk_packages` | `system`, `packages`, `apk` |
| System + packages | `homebrew` | `packages`, `homebrew` |
| System + packages | `termux_packages` | `system`, `packages`, `termux` |
| System + packages | `bitwarden` | `secrets`, `bitwarden` |
| System + packages | `shell_fonts` | `dotfiles`, `shell`, `fonts` |
| System + packages | `shell_dotfiles` | `dotfiles`, `shell`, `dotfiles` |
| System + packages | `pi` | `dotfiles`, `pi` |
| System + packages | `hive_ops` | `hive`, `hive_ops` |
| System + packages | `git` | `dotfiles`, `git` |
| System + packages | `neovim` | `dotfiles`, `neovim`, `editor` |
| Secrets + auth | `shell_atuin` | `dotfiles`, `shell`, `atuin`, `secrets` |
| Secrets + auth | `shell_ai` | `dotfiles`, `shell`, `ai`, `secrets` |
| Secrets + auth | `ssh_keys` | `secrets`, `ssh`, `ssh_keys` |
| Secrets + auth | `ssh_mesh` | `ssh`, `mesh_check` |
| Secrets + auth | `github` | `secrets`, `github` |
| Secrets + auth | `tailscale` | `secrets`, `tailscale` |
| Secrets + auth | `kube` | `secrets`, `kube` |
| Secrets + auth | `forgejo_registry` | `secrets`, `forgejo`, `registry` |
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
| Services | `server_hardening` | `system`, `hardening`, `security` |
| Services | `fleet_facts` | `facts`, `fleet_facts` |

Common phase-wide selections:

- `--tags secrets` — every BW-backed role only (`bitwarden`, `shell_atuin`, `shell_ai`, `ssh_keys`, `github`, `tailscale`, `kube`, `forgejo_registry`)
- `--tags desktop` — every desktop-app role (`flatpak`, `bluefin_common`, `gnome`, `zen_browser`, `pipewire_audio`)
- `--tags services` — every long-running service role (`syncthing`, `systemd`, `bst_dashboard`, `kirocrew`, `proxy`, `tailscale_cert`)
- `--skip-tags secrets` — everything except BW-backed roles (what `apply-nosecrets`/`dots` use)

Tags do not replace the `skip_*` host_vars flags or inventory-group gating described below — a role can be tag-selected and still no-op if its `when:` condition (group membership, `skip_*`, `machine_profile`) evaluates false.

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

## Secrets Flow

1. Ansible requests a Bitwarden session (env var, cached file, or interactive unlock)
2. The `bitwarden` role resolves `BW_SESSION` and caches it
3. Secrets-tagged roles consume the session token for API calls
4. For remote applies, `scripts/bw-resolve.sh remote <host>` unlocks the vault on the target and the recipe exports that session inline over `ssh -t` (no `SendEnv`) — see [Remote Apply](bitwarden.md#remote-apply)

No secrets are stored in git — the repo is fully public.
