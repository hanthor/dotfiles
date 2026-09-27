# Utility Scripts

The `scripts/` directory contains helper utilities for inventory management, Bitwarden integration, and operational tasks. They are not deployed to machines — they run on your local development machine or during CI.

## Inventory Management

### `register-machine.py`

Register a new machine in `inventory.yml` and create its `host_vars` file.

**Usage:**
```bash
python3 scripts/register-machine.py <name> [type] [path-to-inventory.yml]
```

**Arguments:**
- `<name>` — machine name (e.g., `kanpur`, `goa`)
- `[type]` — group/machine type: `desktop`, `server`, `vps`, `termux_hosts` (default: `desktop`)
- `[path-to-inventory.yml]` — inventory file path (default: `inventory.yml`)

**What it does:**
- Adds the machine to the `all.hosts` section
- Adds it to the specified group under `all.children`
- Sets `ansible_host: localhost` and `ansible_connection: local`
- Creates `host_vars/<name>.yml` with a template

**Example:**
```bash
python3 scripts/register-machine.py goa server
```

### `purge-machine.py`

Remove a machine from `inventory.yml` and its `host_vars` file. Mirror of `register-machine.py`.

**Usage:**
```bash
python3 scripts/purge-machine.py <name> [path-to-inventory.yml]
```

**Important:** Does NOT delete the corresponding Bitwarden SSH key item — you can re-onboard the machine later using the same name.

**Example:**
```bash
python3 scripts/purge-machine.py matrix
```

### `nmap-inventory.sh`

Scan the LAN using `nmap` and cross-reference with Tailscale to show network status.

**Usage:**
```bash
./scripts/nmap-inventory.sh [CIDR]
```

**Arguments:**
- `[CIDR]` — network range to scan (default: `192.168.0.0/24`). Override with a different subnet.

**Output columns:**
- IP address
- MAC address
- Hostname (reverse DNS or nmap service detection)
- Tailscale status (online/offline)

**Prerequisites:**
- `nmap` installed
- Tailscale running and authenticated
- Network access to the scanned range

**Example:**
```bash
./scripts/nmap-inventory.sh 10.0.0.0/24
```

## Bitwarden Integration

### `bw-resolve.sh`

Resolve a usable `BW_SESSION` for local and remote operations. Tries multiple fallback tiers.

**Usage:**
```bash
./scripts/bw-resolve.sh local
./scripts/bw-resolve.sh remote <host>
```

**Modes:**

- **`local`** — Resolve a session on your local machine. Returns `export BW_SESSION=...` on stdout or exits 1 if unlock fails.

- **`remote <host>`** — Unlock Bitwarden on a remote machine, export that session inline over `ssh -t`, and return it. Used by `just apply-remote` to drive secret-dependent tasks on the target.

**Session resolution order:**
1. Existing `BW_SESSION` environment variable (if still valid)
2. Cached session in `/tmp/bw_session` (if not expired)
3. Interactive `bw unlock` prompt (asks for master password)

**Example — local:**
```bash
eval "$(./scripts/bw-resolve.sh local)"
bw list items  # Now BW_SESSION is set
```

**Example — remote:**
```bash
./scripts/bw-resolve.sh remote himachal
# Executes commands on himachal with Bitwarden access
```

### `bw-unlock.sh`

Simpler variant of `bw-resolve.sh` — resolves a session on the local machine only.

**Usage:**
```bash
./scripts/bw-unlock.sh
```

**Output:** Prints `<session-token>` on stdout, or exits 1 if all tiers fail.

### `bw-seed-ssh-keys.sh`

Pull SSH public keys from all online machines and seed them into a Bitwarden collection.

**Usage:**
```bash
./scripts/bw-seed-ssh-keys.sh
```

**What it does:**
- Connects to each machine in the online fleet
- Retrieves their `~/.ssh/id_ed25519.pub`
- Creates Bitwarden login items named `james@<hostname>` with the public key in the password field
- Updates existing items in place (safe to re-run)

**Prerequisites:**
- SSH access to all machines (keys already in `~/.ssh/authorized_keys`)
- Bitwarden CLI (`bw`) authenticated
- Tailscale or direct network access to all machines

**Run once:** Before onboarding a new machine, so their SSH keys are available in Bitwarden during setup.

### `bw-seed-kube.sh`

Seed kubeconfig and talosconfig from this machine into Bitwarden.

**Usage:**
```bash
./scripts/bw-seed-kube.sh
```

**What it does:**
- Exports your local `~/.kube/config` to Bitwarden as a secure note
- Exports your local `~/.talos/config` to Bitwarden
- Updates existing items in place

**Prerequisites:**
- kubectl configured with cluster access
- talosctl configured with cluster access
- Bitwarden CLI (`bw`) authenticated

**Use when:** You've set up cluster access locally and want to share it to other machines.

## Apply and Status

### `record-apply.py`

Record the outcome of a `just apply` run for tracking and status checks.

**Usage:**
```bash
python3 scripts/record-apply.py <exit-code> [label] [skip-tags]
```

**Arguments:**
- `<exit-code>` — exit code from the Ansible apply (0 = success, non-zero = failure)
- `[label]` — optional descriptive label (default: inferred from context)
- `[skip-tags]` — optional comma-separated skip tags (for partial applies)

**Output:** Writes to `~/.cache/dotfiles/last-apply.json` with:
- Timestamp
- Exit code (0 = success, 1 = failure)
- Label and skip tags (if provided)

**Used by:** `just doctor` to check health status and flag old or failed applies.

### `last-apply-status.py`

Pretty-print the last recorded apply status. Used by `just doctor`.

**Usage:**
```bash
python3 scripts/last-apply-status.py
```

**Exit codes:**
- `0` — apply succeeded and timestamp is recent (< 48 hours)
- `1` — apply failed OR timestamp is stale (≥ 48 hours)

**Output:** Human-readable status with timestamp, result, and any tags.

### `online_hosts.py`

Print the list of online fleet hosts (intersection of Tailscale peers and inventory), excluding VPS machines and localhost.

**Usage:**
```bash
python3 scripts/online_hosts.py
```

**Output:** One hostname per line.

**Used by:** `just _online_hosts` and bulk apply operations to target only reachable machines.

**Silently fails:** If Tailscale is not running, returns empty output (so scripts gracefully degrade).

## Cluster and Infrastructure

### `kubevirt-node`

Operations on KubeVirt nodes for the test cluster.

**Usage:**
```bash
./scripts/kubevirt-node [command] [node-name]
```

**Supported commands:**
- `list` — List all KubeVirt test nodes
- `start <node>` — Power on a node
- `stop <node>` — Power off a node
- `status <node>` — Show node status

**Prerequisites:**
- `kubectl` configured with cluster access
- Permission to manage VirtualMachine resources

### `sync-brews.sh`

Sync the Homebrew package state: fetch the current installed packages from Homebrew and update `group_vars/all.yml` with the new list.

**Usage:**
```bash
./scripts/sync-brews.sh
```

**What it does:**
1. Runs `brew list --formulae` and `brew list --casks`
2. Extracts the current package list
3. Updates the `homebrew_packages` and `homebrew_casks` sections in `group_vars/all.yml`
4. Prints a diff so you can review changes

**Use when:** You've manually installed packages with `brew install` and want to record them in the inventory for automated management.

### `ess-render-values.py`

Render Helm values for the AWS Talos cluster (ESS) by applying substitution rules from Bitwarden.

**Usage:**
```bash
python3 scripts/ess-render-values.py < ess-helm-values-template.yml > values.yml
```

**What it does:**
1. Reads the `ess-helm-values` secure note from Bitwarden
2. Applies environment and variable substitutions (e.g., `${DOMAIN}`)
3. Outputs the rendered Helm values to stdout

**Used by:** Cluster deployment pipelines to generate final Helm configurations.

**Prerequisites:**
- `bw` CLI authenticated with Bitwarden vault access
- The `ess-helm-values` secure note exists in Bitwarden

## Prerequisites and Setup

All scripts assume:
- **Python 3** (for `.py` scripts)
- **Bash** (for `.sh` scripts)
- **Bitwarden CLI** (`bw`) installed and configured when BW scripts are used
- **SSH access** to target machines (for remote operations)
- **Tailscale** installed for machine discovery (for inventory scripts)

Set up Bitwarden CLI once:
```bash
brew install bitwarden-cli  # macOS
# or: apt-get install bw   # Linux

bw login <email>
```

Session tokens are cached locally in `/tmp/` for convenience; they expire and are renewed automatically.
