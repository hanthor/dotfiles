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
    punjab:   # Headless Ubuntu agent box (EC2, us-east-1)
    vm:       # Local dev VM
    goa:      # Raspberry Pi 5 (ARM)
```

Server roles: `server_hardening`, plus the service roles.

### `vps`
Hetzner VPSes — **both retired** (migrated to the
[AWS Talos cluster](servers/aws-k8s/cluster.md)) but powered on for burn-in.
Nothing on them may be restarted.

```yaml
vps:
  hosts:
    matrix:     # Retired — former Matrix homeserver
    telengana:  # Retired — formerly lkofoss; hosted the Hive on k3s
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
The raw Termux/Android layer on the phone. Gates the `termux_packages` role.

```yaml
termux_hosts:
  hosts:
    termux:
```

### `llm` (dormant)
Commented out in `inventory.yml` — its only member, karnataka, is now a Talos
worker.

### Not in the inventory

**bihar** and **karnataka** are Talos nodes (no SSH) and are managed with
`talosctl`/`kubectl` only. The home cluster is powered down and in storage,
expected back. The AWS cluster's nodes are likewise not in the inventory.

## Per-Machine Configuration

Each machine has a `host_vars/<name>.yml` file with common knobs:

```yaml
is_arm: false          # ARM architecture
is_laptop: true        # Laptop (runs on login, not timer)
skip_flatpak: true     # Skip Flatpak installs
skip_gnome: true       # Skip GNOME config
skip_kube: true        # Skip kubeconfig deploy
skip_proxy: true       # Skip Caddy proxy
machine_profile: cli-only  # Free-form profile; `vm-test` skips desktop + service roles
web_services: []       # Service links for the local dashboard
```

The full set of `skip_*` flags `site.yml` honours: `skip_sudo`, `skip_ssh_mesh`,
`skip_kube`, `skip_forgejo`, `skip_flatpak`, `skip_bluefin`, `skip_gnome`,
`skip_zen_browser`, `skip_pipewire_audio`, `skip_syncthing`, `skip_systemd`,
`skip_proxy`, `skip_tailscale_cert`.

## Group Variables

- **`group_vars/all.yml`** — Homebrew package lists, Flatpak remotes, Firefox Accounts config, GNOME extensions, authorized SSH keys
- **`roles/flatpak/vars/main.yml`** — the `system_flatpaks` list
- **`group_vars/vps.yml`** — currently empty
