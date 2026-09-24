# Dotfiles Fleet Handbook

[Introduction](index.md)

# Core Concepts

- [Architecture](architecture.md)
- [Inventory & Groups](inventory.md)
- [Secrets with Bitwarden](bitwarden.md)
- [Onboarding a New Machine](onboarding.md)
- [QR Secret Onboarding](qr-onboarding.md)
- [Operational Runbook](runbook.md)

# Fleet Reference

- [Network](network.md)
  - [Gateway](network/gateway/README.md)
  - [Phone](network/phone/README.md)
  - [Printer](network/printer/README.md)
  - [ESP32](network/esp32/README.md)
  - [MacBook](network/macbook/README.md)
  - [KVM](network/kvm/README.md)
- [Desktops]()
  - [Dilli](desktop/dilli/README.md)
  - [Himachal](desktop/himachal/README.md)
  - [Kanpur](desktop/kanpur/README.md)
  - [Kerala](desktop/kerala/README.md)
- [Servers]()
  - [Goa](servers/goa/README.md)
  - [Punjab (AWS)](servers/punjab/README.md)
  - [Talos K8s Cluster (offline)](servers/talos-k8s/cluster.md)
    - [Bihar](servers/talos-k8s/bihar/README.md)
    - [Karnataka](servers/talos-k8s/karnataka/README.md)
  - [AWS Account & IaC](servers/aws/README.md)
  - [AWS Talos Cluster](servers/aws-k8s/cluster.md)
- [VPS]()
  - [Matrix (retired)](vps/matrix/README.md)
  - [Telengana (retired)](vps/telengana/README.md)

# Roles Reference

## System

- [sshd](roles/sshd.md)
- [sudo](roles/sudo.md)
- [apk_packages](roles/apk_packages.md)
- [server_hardening](roles/server_hardening.md)

## Packages

- [homebrew](roles/homebrew.md)
- [flatpak](roles/flatpak.md)
- [termux_packages](roles/termux_packages.md)

## Dotfiles

- [shell_fonts](roles/shell_fonts.md)
- [shell_dotfiles](roles/shell_dotfiles.md)
- [shell_atuin](roles/shell_atuin.md)
- [shell_ai](roles/shell_ai.md)
- [pi](roles/pi.md)
- [hive_ops](roles/hive_ops.md)
- [git](roles/git.md)
- [neovim](roles/neovim.md)

## Secrets & Auth

- [bitwarden](roles/bitwarden.md)
- [ssh_keys](roles/ssh_keys.md)
- [ssh_mesh](roles/ssh_mesh.md)
- [github](roles/github.md)
- [tailscale](roles/tailscale.md)
- [kube](roles/kube.md)
- [forgejo_registry](roles/forgejo_registry.md)

## Desktop

- [gnome](roles/gnome.md)
- [zen_browser](roles/zen_browser.md)
- [browser_fxa](roles/browser_fxa.md)
- [bluefin_common](roles/bluefin_common.md)
- [pipewire_audio](roles/pipewire_audio.md)

## Services

- [syncthing](roles/syncthing.md)
- [systemd](roles/systemd.md)
- [proxy (Caddy)](roles/proxy.md)
- [tailscale_cert](roles/tailscale_cert.md)
- [bst_dashboard](roles/bst_dashboard.md)

## Removed / migrated

- [appflowy](roles/appflowy.md)
- [authentik](roles/authentik.md)
- [n8n](roles/n8n.md)

# Cluster

- [Talos Kubernetes](talos-k8s.md)
- [Hive Agent Supervisor](cluster/hive.md)
