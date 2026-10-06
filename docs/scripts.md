# Utility Scripts Reference

The `scripts/` directory contains utility scripts for inventory management, Bitwarden seeding, cluster operations, and configuration tracking. Each script handles a specific operational concern.

## Table of Contents

- [Inventory Management](#inventory-management)
- [Bitwarden Integration](#bitwarden-integration)
- [Cluster & Infrastructure](#cluster--infrastructure)
- [Application State Tracking](#application-state-tracking)
- [Package Management](#package-management)

---

## Inventory Management

These scripts manage the Ansible inventory and track which machines are available.

### `register-machine.py`

Register a new machine in the inventory and create its host variables file.

**Purpose**: Add a new machine to the Ansible inventory, creating the necessary entries in `inventory.yml` and initializing a `host_vars/<name>.yml` file for machine-specific configuration.

**Usage**:
```bash
./scripts/register-machine.py <name> [type] [inventory-path]
```

**Arguments**:
- `<name>` — machine name (required, e.g., `karnataka`, `himachal`)
- `[type]` — machine type/group (default: `desktop`; options: `desktop`, `server`, `vps`, or any group in your inventory)
- `[inventory-path]` — path to `inventory.yml` (default: `inventory.yml`)

**Examples**:
```bash
# Register a desktop machine
./scripts/register-machine.py karnataka desktop

# Register a VPS
./scripts/register-machine.py goa vps

# Register with custom inventory
./scripts/register-machine.py bihar server ~/my-inventory.yml
```

**Prerequisites**: None; uses only Python stdlib.

**What it does*es the YAML inventory file
2. Adds the machine to the specified group (or errors if the group doesn't exist)
3. Creates a new `host_vars/<name>.yml` file with templated content
4. Does not touch Bitwarden or SSH keys

**Related**: `purge-machine.py` (inverse operation)

---

### `purge-machine.py`

Remove a machine from the inventory and its host variables file.

**Purpose**: Decommission a machine by removing it from `inventory.yml` and deleting its `host_vars/<name>.yml` file. Does NOT delete Bitwarden items, so the SSH key (`james@<name>`) remains for re-onboarding.

**Usage**:
```bash
./scripts/purge-machine.py <name> [inventory-path]
```

**Arguments**:
- `<name>` — machine name (required)
- `[inventory-path]` — path to `inventory.yml` (default: `inventory.yml`)

**Examples**:
```bash
./scripts/purge-machine.py karnataka
./scripts/purge-machine.py bihar ~/my-inventory.yml
```

**Prerequisites**: None; uses only Python stdlib.

**What it does**:
1. Finds and removes the machine from its group in the inventory
2. Deletes the corresponding `host_vars/<name>.yml` file
3. Leaves Bitwarden items intact (`james@<name>` SSH key and any other secrets)

**Safety**: The SSH key is preserved so you can re-register the same name later without re-seeding Bitwarden.

**Related**: `register-machine.py`

---

### `nmap-inventory.sh`

Scan the local network and report host availability with Tailscale status.

**Purpose**: Discover machines on a local subnet and cross-reference them with Tailscale peer status. Useful for network diagnostics and verifying machine reachability.

**Usage**:
```bash
./scripts/nmap-inventory.sh [subnet]
```

**Arguments**:
- `[subnet]` — network CIDR (default: `192.168.0.0/24`)

**Examples**:
```bash
# Scan default subnet
./scripts/nmap-inventory.sh

# Scan different subnet
./scripts/nmap-inventory.sh 10.0.0.0/24

# Scan a /16
./scripts/nmap-inventory.sh 172.16.0.0/16
```

**Prerequisites**:
- `nmap` (install via `brew install nmap`)
- `tailscale` CLI (for Tailscale status lookup)

**Output**:
```
IP               MAC                 Hostname               Vendor                       Tailscale
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
192.168.0.50     aa:bb:cc:dd:ee:ff   karnataka              Intel Corporate             karnataka (online)
192.168.0.51     11:22:33:44:55:66   himachal               NVIDIA                      himachal (offline)
```

**What it does**:
1. Runs `nmap -sn` on the specified subnet
2. Parses the XML output for IP, MAC, and hostname
3. Looks up each IP in `tailscale status --json`
4. Prints a table sorted by IP address

**Notes**:
- Requires `sudo` for accurate MAC address resolution (falls back without it)
- Scans the network without connecting to each host (ping-only)

---

### `online_hosts.py`

List machines currently online: Tailscale peers that are in the inventory, excluding VPSs and the local machine.

**Purpose**: Identify which real machines (desktops/servers, not cloud VPSs) are reachable via Tailscale. Used by the Justfile to target apply runs.

**Usage**:
```bash
./scripts/online_hosts.py
```

**Output**:
```
karnataka
himachal
bihar
```

**Prerequisites**:
- `tailscale` CLI
- Populated `inventory.yml` in the current directory (or at the repo root)

**What it does**:
1. Queries `tailscale status --json` for online peers
2. Parses `inventory.yml` to find all machines and their groups
3. Returns the intersection: machines that are both online and in inventory
4. Excludes VPS group and the local machine (by hostname)

**Related**: Used by the Justfile's `_online_hosts` task for targeting group apply runs.

---

## Bitwarden Integration

These scripts seed and manage secrets in Bitwarden, and provide helpers for accessing them.

### `bw-seed-ssh-keys.sh`

Pull SSH keys from all machines and seed them into Bitwarden, then write `authorized_keys`.

**Purpose**: Centralize SSH public/private key pairs in Bitwarden for secure backup and recovery, and synchronize all public keys to `dot_ssh/authorized_keys` for deployment via chezmoi.

**Usage**:
```bash
./scripts/bw-seed-ssh-keys.sh              # all machines
./scripts/bw-seed-ssh-keys.sh karnataka   # single machine
./scripts/bw-seed-ssh-keys.sh goa bihar   # multiple machines
```

**Prerequisites**:
- Bitwarden CLI (`bw`) and authentication: `bw login` if not already authenticated
- SSH access to all target machines
- `jq` for JSON processing
- `gh` CLI (for GitHub key registration)

**What it does**:
1. Unlocks Bitwarden (or prompts for master password)
2. For each machine:
   - Looks for `~/.ssh/<machine>_id_ed25519` or `~/.ssh/id_ed25519`
   - Fetches the local key or SSHes to the remote to fetch it
   - Creates or updates a Bitwarden SSH Key item named `<machine>`
   - Registers the public key with GitHub (both auth and signing)
3. Collects all public keys and writes `dot_ssh/authorized_keys`
4. Prints instructions to commit and push

**Output**:
```
── karnataka (karnataka) ──
  ✓ Keys fetched (pub: AAAAB3NzaC1yc2E...)
  ✓ GitHub auth key registered.
  ✓ GitHub signing key already registered.

── himachal (himachal) ──
  ✓ Keys fetched (pub: AAAAB3NzaC1yc2E...)
  ✓ GitHub auth key already registered.
  ✓ GitHub signing key already registered.

Written: /Users/james/dotfiles/dot_ssh/authorized_keys
  → 42 lines, 2 machine(s)

Commit and push to deploy to all machines:
  cd /Users/james/dotfiles && git add dot_ssh/authorized_keys && git commit -m 'chore: update authorized_keys' && git push
```

**Common Workflows**:
- First setup: run once to seed all machines' keys
- Adding a new machine: run with the new machine name after `register-machine.py` and SSH is configured
- Machine compromised: run with that machine to refresh its key across Bitwarden and GitHub

---

### `bw-seed-kube.sh`

Seed Bitwarden with kubeconfig and talosconfig from the local machine.

**Purpose**: Back up Kubernetes and Talos cluster access files to Bitwarden for secure storage and team recovery.

**Usage**:
```bash
./scripts/bw-seed-kube.sh
```

**Prerequisites**:
- Bitwarden CLI (`bw`) and authentication
- `KUBECONFIG` and/or `TALOSCONFIG` environment variables (or files at `~/.kube/config` and `~/.talos/config`)

**What it does**:
1. Unlocks Bitwarden
2. Reads `$KUBECONFIG` (default: `~/.kube/config`)
3. Reads `$TALOSCONFIG` (default: `~/.talos/config`)
4. Creates or updates Bitwarden Secure Note items:
   - `kubeconfig`
   - `talosconfig`
5. Prints summary and sync instructions

**Notes**:
- Safe to run repeatedly; updates items in place
- Requires `BW_SESSION` or will unlock interactively

---

### `bw-item.sh`

Helper function library for finding and upserting Bitwarden items.

**Purpose**: Shared utility for other scripts; provides `bw_upsert_item()` and `bw_find_item_id()` functions for consistent Bitwarden operations.

**Usage** (source in other scripts):
```bash
source "$(dirname "$0")/bw-item.sh"

# Create or update an item
item_json=$(jq -n '{type:5, name:"my-key", sshKey:{privateKey:"...", publicKey:"..."}}')
bw_upsert_item "my-key" "$item_json" "5"

# Find an item's ID
item_id=$(bw_find_item_id "my-key")
```

**Functions**:
- `bw_find_item_id <name> [type-filter]` — find a Bitwarden item by exact name, optionally filtered by type
- `bw_upsert_item <name> <item_json> [type]` — create or update an item with the given JSON

**Requirements**: `BW_SESSION` must be exported; requires `bw` and `jq`.

---

### `bw-unlock.sh`

Resolve a Bitwarden session locally and print it to stdout.

**Purpose**: Provide a consistent way to unlock Bitwarden and export `BW_SESSION` for use in other scripts, with caching support.

**Usage**:
```bash
export BW_SESSION=$(./scripts/bw-unlock.sh)
```

**Exit Codes**:
- `0` — session printed to stdout (use it)
- `2` — `bw` CLI not installed
- `3` — vault is unauthenticated (`bw login` needed first)
- `4` — interactive unlock failed

**What it does**:
1. Checks `BW_SESSION` env variable
2. Checks `/tmp/bw_session` cache (if still valid)
3. Prompts for interactive unlock if needed
4. Caches the session to `/tmp/bw_session` (mode `0600`)
5. Prints the session to stdout

**Caching**: Reuses cached sessions across runs, so you only unlock once per session.

---

### `bw-resolve.sh`

Resolve a Bitwarden session either locally or on a remote machine.

**Purpose**: More flexible than `bw-unlock.sh`; supports remote unlock via SSH and three resolution modes.

**Usage**:
```bash
./scripts/bw-resolve.sh local              # local session (same as bw-unlock.sh)
./scripts/bw-resolve.sh remote <host>     # SSH to host and resolve there
./scripts/bw-resolve.sh                    # default = local
```

**Exit Codes**:
- `0` — session resolved
- `1` — no session available

**Modes**:
- **local**: Uses the standard unlock chain (env → cache → interactive). Prints `export BW_SESSION=...` for eval.
- **remote**: SSHes to `<host>`, attempts API key login (if unauthenticated), non-interactive unlock, then interactive. Prints just the token.
- **no args**: Alias for "local".

**Example**:
```bash
# Local: unlock and export
eval "$(./scripts/bw-resolve.sh local)"

# Remote: get session from another machine
BW_SESSION=$(./scripts/bw-resolve.sh remote karnataka)
bw list items --session "$BW_SESSION"
```

---

## Cluster & Infrastructure

### `kubevirt-node`

Power the AWS KubeVirt node up or down from the tailnet.

**Purpose**: Manage the AWS EC2 instance running the KubeVirt migration cluster, which is automatically scaled down after 30 idle minutes or when compute credits are low.

**Usage**:
```bash
./scripts/kubevirt-node up      # start and wait for Ready
./scripts/kubevirt-node down    # stop gracefully
./scripts/kubevirt-node status  # current state
```

**Prerequisites**:
- AWS CLI configured with credentials
- `kubectl` with access to the AWS migration cluster
- `KUBECONFIG` pointing to `~/.kube/config-aws-migration` (or set explicitly)

**What it does**:
- **up**: Starts the EC2 instance and waits for the Kubernetes node to report Ready
- **down**: Stops the EC2 instance gracefully (VMs on it are shut down first by the cluster)
- **status**: Prints the current EC2 state (running, stopped, pending, etc.)

**Notes**:
- The cluster runs an idle-stop CronJob that automatically stops after 30 idle minutes
- A migration budget controller stops it if credits approach limits
- Daily workflow: just run `up` in the morning; `down` is automatic

---

### `ess-render-values.py`

Render production ESS Helm values from Bitwarden and output for `helm` command.

**Purpose**: Dynamically generate Helm values for the ESS (Element Server Suite) Synapse deployment, injecting secrets (Matrix signing key, Postgres passwords) from Bitwarden without touching disk.

**Usage**:
```bash
bw get notes <ess-helm-values-id> \
  | ./scripts/ess-render-values.py \
  | helm upgrade --install ess oci://ghcr.io/element-hq/ess-helm/matrix-stack \
      --version 26.8.1 -n ess -f -
```

**Prerequisites**:
- Bitwarden CLI and authenticated vault
- `helm` CLI
- Synapse signing key and Postgres passwords stored in a Bitwarden Secure Note

**What it does**:
1. Reads the ESS Helm values template from stdin (as a Bitwarden Secure Note)
2. Applies cutover substitutions (cluster-specific changes)
3. Writes the rendered YAML to stdout (never touches disk)
4. Safe for pipes to `helm` directly

**Security**: Values contain sensitive data (Synapse signing key, Postgres password) inline — never save to disk, only pipe.

---

## Application State Tracking

These scripts record the outcome of Ansible apply runs and check if the system is in a converged state.

### `record-apply.py`

Record the outcome of an Ansible apply run to `~/.cache/dotfiles/last-apply.json`.

**Purpose**: Track whether the most recent `ansible-playbook` run succeeded or failed, and with which configuration tags and skips. Used by `just doctor` to report convergence freshness.

**Usage**:
```bash
# Called automatically by Justfile:
./scripts/record-apply.py <exit-code> [label] [skip-tags]
```

**Arguments**:
- `<exit-code>` — the exit code from the ansible-playbook run (required)
- `[label]` — descriptive label (default: none; e.g., `full apply`, `desktop only`)
- `[skip-tags]` — comma-separated skip-tags used (e.g., `slow,download`)

**Examples**:
```bash
# Record a successful apply
./scripts/record-apply.py 0 "full apply"

# Record a failed apply with skips
ansible-playbook main.yml --skip-tags slow; ./scripts/record-apply.py $? "desktop" "slow"
```

**Output** (`~/.cache/dotfiles/last-apply.json`):
```json
{
  "exit_code": 0,
  "timestamp": 1696550400,
  "label": "full apply",
  "skip_tags": "",
  "git_branch": "main",
  "git_sha": "abc1234..."
}
```

**Related**: `last-apply-status.py` (reads this file)

---

### `last-apply-status.py`

Pretty-print the outcome of the most recent apply run and exit with status.

**Purpose**: Check if the system is in a converged, up-to-date state. Used by `just doctor` to flag convergence issues.

**Usage**:
```bash
./scripts/last-apply-status.py
```

**Output**:
```
  ✓ Last apply: 2024-10-06 15:30 (main / abc1234, desktop, 2 hours ago)
  ✓ Exit code: 0
```

or

```
  ✗ Last apply: 2024-10-06 15:30 (FAILED)
  ✗ Exit code: 1
```

or

```
  ⚠ last-apply.json not found (or 48+ hours old)
```

**Exit Codes**:
- `0` — apply succeeded and is recent (< 48 hours)
- `1` — apply failed or is stale (> 48 hours)
- `2` — no apply recorded (file not found or corrupted)

**Related**: `record-apply.py` (writes this file)

---

## Package Management

### `sync-brews.sh`

Sync currently installed Homebrew packages to `group_vars/all.yml`.

**Purpose**: Keep the Ansible group variables in sync with the actual installed packages, so you can track package changes and automate Homebrew reinstalls via Ansible.

**Usage**:
```bash
./scripts/sync-brews.sh
```

**Prerequisites**:
- Homebrew installed (`/home/linuxbrew/.linuxbrew/bin/brew`)
- `yq` CLI for YAML manipulation
- `group_vars/all.yml` with `core_brews` and `desktop_brews` lists

**What it does**:
1. Runs `brew bundle dump` to capture the current Homebrew state
2. Parses `group_vars/all.yml` for existing `core_brews` and `desktop_brews` lists
3. For each package not already in either list, adds it to `desktop_brews`
4. Updates the file in place (surgically, using `yq -i`)

**Output**:
```
Fetching current Homebrew state...
Adding new package to desktop_brews: ripgrep
Adding new package to desktop_brews: fzf
Done! group_vars/all.yml updated surgically.
```

**Use Cases**:
- After installing packages manually with `brew install`, run this to record them
- Then commit `group_vars/all.yml` so other machines can `brew bundle install` the same packages
- Useful for keeping installations in sync across desktops

---

## Common Workflows

### Onboarding a New Machine

1. Run `register-machine.py`:
   ```bash
   ./scripts/register-machine.py karnataka desktop
   ```
   Creates inventory entry and `host_vars/karnataka.yml`.

2. Configure SSH access to the new machine.

3. Run `bw-seed-ssh-keys.sh` to back up its SSH keys:
   ```bash
   ./scripts/bw-seed-ssh-keys.sh karnataka
   ```

4. Deploy via chezmoi:
   ```bash
   chezmoi init https://github.com/hanthor/dotfiles
   chezmoi apply
   ```

### Checking System Convergence

1. Run `just doctor` (which calls `last-apply-status.py`)
2. If stale (> 48 hours), run an apply:
   ```bash
   just apply
   ```

### Finding Online Machines

```bash
# See which machines are currently reachable
./scripts/online_hosts.py

# Use in a Justfile or script
for host in $(./scripts/online_hosts.py); do
  echo "Applying to $host..."
  just apply-host $host
done
```

### Network Diagnostics

```bash
# Scan the local LAN and see Tailscale status
./scripts/nmap-inventory.sh

# Custom subnet
./scripts/nmap-inventory.sh 10.0.0.0/24
```

---

## Troubleshooting

**"bw not installed"**
- Install: `brew install bitwarden-cli`
- Verify: `bw --version`

**"Unknown machine type/group 'foo'"**
- Check your `inventory.yml`; `register-machine.py` requires the group to already exist
- Example groups: `desktop`, `server`, `vps`

**"SSH unreachable"**
- `nmap-inventory.sh` and `bw-seed-ssh-keys.sh` both need SSH access to remote machines
- Verify SSH connectivity: `ssh james@<hostname>`

**"Bitwarden vault is unauthenticated"**
- Run `bw login` first, or set `BW_SESSION` if you have an active session

**"no aws-migration-kubevirt instance"**
- Check AWS region: `kubevirt-node` defaults to `eu-north-1`
- Set `AWS_DEFAULT_REGION` if your instance is elsewhere

