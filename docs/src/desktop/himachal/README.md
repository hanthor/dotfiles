# Himachal

Laptop workstation in the hanthor fleet.

## Hardware and OS

- Architecture: x86_64
- OS: [Bluefin](https://projectbluefin.io/)
- The reachable Tailscale SSH name used for the 2026-10-27 inspection was
  `james@himachal-1` (hostname `himachal`). The inventory entry for `himachal`
  still specifies `100.73.3.51`; it should not be assumed to identify the
  reachable node without checking.

## Native dotfiles validation

On 2026-10-28, the PR #348 branch was applied with `--no-secrets --tags
dotfiles` to `himachal-1`. Bash and headless Neovim started, and the omp broker
status check succeeded. The apply also ran the Neovim plugin sync script.
Atuin was not logged in; its secret-bearing login was not tested. Unlock the
local Bitwarden vault and apply the `atuin` tag to configure sync.

A mode-0600 pre-apply backup is at
`~/backups/dotfiles-pre-native-20261028T041910Z.tgz`. It includes the omp
configuration and must be treated as secret-bearing. This validation does not
establish that the full fleet or automatic updates have been migrated.

## Services

- **Dotfiles updates:** `host_vars/himachal.yml` sets `is_laptop: true` and
  `dotfiles_auto_update: false`. On 2026-10-27, `dotfiles-update.service` was
  not found on `himachal-1`. The configured 90-second delay applies only if
  login-time automatic updates are enabled; it is not evidence that updates
  currently run. The host-vars comment suggests `just apply-nosecrets` for a
  manual update.
- **Hive operations:** `hive_ops_enabled: false` in host vars. Read-only
  inspection on 2026-10-27 found the seven former Hive and pi peak timers
  `not-found` and inactive on `himachal-1`. They previously targeted AWS
  Kubernetes, which was terminated on 2026-10-25; the host-vars comment saying
  those jobs now run in-cluster is stale. See
  [hive_ops](../../roles/hive_ops.md) and the
  [current Hive deployment](../../cluster/hive.md#current-deployment-spindle-vps).

The fleet's GNOME role includes [PaperWM](https://github.com/paperwm/PaperWM),
PaperShell and Copyous; their enabled state on this host was not checked.
