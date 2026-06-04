# Dotfiles Fleet Handbook

[Introduction](index.md)

# Core Concepts

- [Architecture](architecture.md)
- [Inventory & Groups](inventory.md)
- [Secrets with Bitwarden](bitwarden.md)
- [Onboarding a New Machine](onboarding.md)

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
  - [Talos K8s Cluster](servers/talos-k8s/cluster.md)
    - [Bihar](servers/talos-k8s/bihar/README.md)
    - [Karnataka](servers/talos-k8s/karnataka/README.md)
- [VPS]()
  - [lkofoss](vps/lkofoss/README.md)
  - [Matrix](vps/matrix/README.md)

# Roles Reference

## System

- [sshd](roles/sshd.md)
- [sudo](roles/sudo.md)
- [apk_packages](roles/apk_packages.md)
- [server_hardening](roles/server_hardening.md)

## Packages

- [homebrew](roles/homebrew.md)
- [flatpak](roles/flatpak.md)

## Dotfiles

- [shell](roles/shell.md)
- [pi](roles/pi.md)
- [git](roles/git.md)
- [neovim](roles/neovim.md)

## Secrets & Auth

- [bitwarden](roles/bitwarden.md)
- [ssh_keys](roles/ssh_keys.md)
- [github](roles/github.md)
- [tailscale](roles/tailscale.md)
- [kube](roles/kube.md)

## Desktop

- [gnome](roles/gnome.md)
- [zen_browser](roles/zen_browser.md)
- [browser_fxa](roles/browser_fxa.md)
- [bluefin_common](roles/bluefin_common.md)
- [easyeffects](roles/easyeffects.md)

## Services

- [syncthing](roles/syncthing.md)
- [systemd](roles/systemd.md)
- [proxy (Caddy)](roles/proxy.md)
- [homepage](roles/homepage.md)
- [monitoring](roles/monitoring.md)
- [cockpit](roles/cockpit.md)
- [lima](roles/lima.md)
- [tailscale_cert](roles/tailscale_cert.md)
- [bst_dashboard](roles/bst_dashboard.md)

## Server Applications

- [appflowy](roles/appflowy.md)
- [authentik](roles/authentik.md)
- [n8n](roles/n8n.md)

# Cluster

- [Talos Kubernetes](talos-k8s.md)
- [Hive Agent Supervisor](cluster/hive.md)
