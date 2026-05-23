# dotfiles

Ansible-managed dotfiles for every machine I own. One command to go from a fresh install to a fully configured system. No central server — each machine manages itself locally, secrets stay in Bitwarden, and everything stays in sync automatically.

```bash
just apply        # full apply with secrets
dots              # quick pull + apply (no secrets)
```

---

## What's included

| Area | What it does |
|------|-------------|
| **Shell** | fish + zsh + tmux configs, shared aliases, SSH client config |
| **Packages** | Homebrew (CLI tools) + Flatpak (desktop apps) |
| **Git** | `~/.gitconfig` with SSH signing, `gh` CLI config |
| **SSH keys** | Per-machine ed25519 keys, synced to/from Bitwarden, cross-machine `authorized_keys` |
| **Tailscale** | Auto-joins the network using a stored auth key |
| **Atuin** | Shell history sync key fetched from Bitwarden |
| **GitHub** | Auth + signing keys registered automatically |
| **GNOME** | Keyboard shortcuts, Ptyxis terminal config |
| **Syncthing** | Systemd user service for file sync |
| **Auto-update** | Systemd timer pulls and applies changes daily |

---

## Day-to-day commands

```bash
just apply             # Pull latest + full apply (prompts for BW unlock)
just apply-nosecrets   # Pull latest + apply without Bitwarden (fast)
just dotfiles          # Only shell/git/tmux configs
just packages          # Only Homebrew + Flatpak
just check             # Dry run — see what would change
just edit-host         # Edit this machine's host_vars
```

Shell aliases available everywhere after first apply:

```bash
dots                   # git pull + apply-nosecrets
dots-secrets           # git pull + full apply with BW unlock
```

---

## Machines

| Name | Type | Host |
|------|------|------|
| karnataka | Desktop (Bluefin) | karnataka |
| kanpur | Desktop (Bluefin) | kanpur |
| himachal | Desktop | himachal |
| dilli | Desktop | dilli |
| bihar | Server (Debian) | bihar |
| matrix | Server | matrix.reilly.asia |
| lkofoss | Server | lkofoss.club |

---

## Security

Repo is public — no secrets in git, ever. All secrets are fetched from Bitwarden at runtime. BW session is forwarded over SSH so you unlock once on your laptop and everything else just works.

---

## Documentation

- [Adding a new machine](docs/new-machine.md)
- [Roles reference](docs/roles.md)
- [Bitwarden vault setup](docs/bitwarden.md)
- [Bluefin-ification guide](BLUEFIN-IFICATION.md)
- [NetBox MCP integration](MCP.md)
