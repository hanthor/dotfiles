# Inventory & Groups

## Host Groups

The inventory defines four functional groups:

### `desktop`
Workstations and laptops with a full desktop environment (GNOME, browsers, etc.).

```yaml
desktop:
  hosts:
    kerala:     # PostMarketOS ARM mobile
    karnataka:  # Main workstation (AMD Strix Halo)
    kanpur:     # Laptop
    himachal:   # Laptop
    dilli:      # Secondary desktop
```

Desktop roles: `flatpak`, `gnome`, `zen_browser`, `bluefin_common`, `easyeffects`

### `server`
Home servers running persistent services.

```yaml
server:
  hosts:
    vm:       # Local dev VM
    bihar:    # Home server (Proxmox host)
    goa:      # ARM server
```

Server roles: `server_hardening`, plus all service roles.

### `vps`
Public-facing virtual private servers.

```yaml
vps:
  hosts:
    matrix:    # Matrix homeserver
    lkofoss:   # Community site
```

VPS-specific overrides in `group_vars/vps.yml`.

### `llm`
Machines with GPU for LLM workloads.

```yaml
llm:
  hosts:
    karnataka:  # AMD Strix Halo APU
```

## Per-Machine Configuration

Each machine has a `host_vars/<name>.yml` file with common knobs:

```yaml
is_arm: false          # ARM architecture
is_laptop: true        # Laptop (runs on login, not timer)
has_homepage: true     # Deploy dashboard
skip_flatpak: true     # Skip Flatpak installs
skip_gnome: true       # Skip GNOME config
skip_kube: true        # Skip kubeconfig deploy
skip_proxy: true       # Skip Caddy proxy
skip_lima: true        # Skip Lima VM manager
web_services: []       # Extra homepage service links
```

## Group Variables

- **`group_vars/all.yml`** — Packages (Homebrew, Flatpak), fleet homepage links, Firefox Accounts config, GNOME extensions, authorized SSH keys
- **`group_vars/vps.yml`** — VPS-specific monitoring and proxy settings
