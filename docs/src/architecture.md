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

Runs only roles tagged with the given tags. Useful for deploying specific configs without running the full playbook.

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
4. For remote applies, the session token is forwarded over SSH via `SendEnv`

No secrets are stored in git — the repo is fully public.
