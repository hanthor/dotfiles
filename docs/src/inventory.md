# Inventory & Groups

## Host Groups

`inventory.yml` defines these groups:

### `desktop`
Workstations and laptops with a full desktop environment (GNOME, browsers, etc.).

```yaml
desktop:
  hosts:
    mumbai:     # Debian VM on the phone (cli-only, skips desktop roles)
    kerala:     # postmarketOS ARM device
    kanpur:     # Laptop
    himachal:   # Laptop (runs hive_ops)
    dilli:      # Secondary desktop
```

Desktop roles: `flatpak`, `gnome`, `zen_browser`, `bluefin_common`, `pipewire_audio`, `kube`

### `server`
Headless hosts.

```yaml
server:
  hosts:
    punjab:   # EC2 agent box (us-east-1; current instance status unverified)
    vm:       # Local dev VM
    goa:      # Raspberry Pi 5 (ARM)
    karnataka: # Utah host; multi-user.target by default
```

Server roles: `server_hardening`, plus the service roles.

### `vps`
The inventory lists two **retired** Hetzner VPSes, formerly migrated to the
[AWS Talos cluster](servers/aws-k8s/cluster.md), which was terminated on
2026-10-25. Restart nothing on these hosts; follow the
[Matrix cutover runbook](https://github.com/hanthor/dotfiles/blob/master/docs/matrix-cutover-runbook.md)
before touching either. Active [spindle](servers/spindle-vps/README.md) is an
OCI Frankfurt VPS running Matrix and standalone LiveKit; it is not in this inventory.

```yaml
vps:
  hosts:
    matrix:     # Retired — former Matrix homeserver
    telengana:  # Retired — hosted the Hive on k3s
```

`vps` members skip `syncthing`, `proxy` and `tailscale_cert`, and get
`server_hardening`. `group_vars/vps.yml` is currently empty.

### `test_fleet`
KubeVirt VMs reached via `virtctl port-forward` (see the host's `host_vars`).
Both set `machine_profile: vm-test`, which skips desktop and service roles.

```yaml
test_fleet:
  hosts:
    test-fleet-fedora:
    test-fleet-node2:
```

### `termux_hosts`
The raw Termux/Android layer on the phone. Gates the `termux-packages` unit.

```yaml
termux_hosts:
  hosts:
    termux:
```

### `llm` (dormant)
Commented out in `inventory.yml`; its only listed member is karnataka.

### Not in the inventory

**Bihar** was recently online but is currently unreachable; its OS and services
are unverified. It is not in the inventory.
The [home Talos reference](servers/talos-k8s/cluster.md), manifests, configs and
Bitwarden notes are retained for historical recovery, not evidence of either
machine's current state. The terminated AWS cluster's nodes were not in the
inventory either.

## Per-Machine Configuration

Each machine has a `host_vars/<name>.yml` file with common knobs:

```yaml
is_laptop: true        # Laptop (runs on login, not timer)
skip_flatpak: true     # Skip Flatpak installs
skip_gnome: true       # Skip GNOME config
skip_kube: true        # Skip kubeconfig deploy
skip_proxy: true       # Skip Caddy proxy
machine_profile: cli-only  # Free-form profile; some units skip `vm-test`
web_services: []       # Service links for the local dashboard
```

Units read their own `skip_*` flags and profile settings; see the relevant
unit under `units/` and [Architecture](architecture.md#conditional-execution).
The flags are not all interpreted identically.

## Group Variables

- **`group_vars/all.yml`** — Homebrew package lists, Flatpak remotes, Firefox Accounts config, GNOME extensions, authorized SSH keys
- **`units/flatpak-packages.yml`** — the `system_flatpaks` list
- **`group_vars/vps.yml`** — currently empty
