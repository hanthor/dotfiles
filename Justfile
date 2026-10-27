# Fleet configuration with mise, bash units and chezmoi
# Usage: just <recipe>

dotfiles_dir := env("HOME") / ".local/share/dotfiles"
machine := `cat /etc/dotfiles-machine 2>/dev/null || hostname`
export PATH := env("HOME") / ".local/bin" + ":/home/linuxbrew/.linuxbrew/bin:" + env("PATH")

# Resolve online fleet hosts: intersect tailscale online peers with inventory (excluding vps + self)
_online_hosts := shell('python3 "$1"', justfile_directory() / "scripts/online_hosts.py")

_secret_tag_pattern := "secrets|ssh|ssh_keys|github|tailscale|kube|forgejo|registry|atuin|ai|omp|desktop|browser|zen_browser|shell|dotfiles"

# Apply all config to this machine (unlocks BW interactively if needed)
apply *args:
    #!/usr/bin/env bash
    set -uo pipefail
    cd {{ dotfiles_dir }} || exit 1
    git pull --ff-only || exit $?
    for arg in {{ args }}; do
      case "$arg" in --upgrade) export DOTFILES_UPGRADE=1 ;; *) echo "Unknown apply option: $arg" >&2; exit 2 ;; esac
    done
    SKIP_TAGS=""
    unit_args=()
    if bw_env=$(scripts/bw-resolve.sh local) && eval "$bw_env" &&
       [ -n "${BW_SESSION:-}" ] && bw unlock --check >/dev/null 2>&1 &&
       timeout 15 bw sync >/dev/null; then
      :
    else
      echo "Bitwarden unavailable or sync failed; continuing without secrets." >&2
      unset BW_SESSION
      SKIP_TAGS=secrets
      unit_args+=(--no-secrets)
    fi
    rc=0; scripts/run-units.sh "${unit_args[@]}" || rc=$?
    scripts/record-apply.py "$rc" apply "$SKIP_TAGS"
    exit "$rc"

# Apply only specific tags (e.g. just apply-tags kube,shell)
apply-tags tags:
    #!/usr/bin/env bash
    set -uo pipefail
    cd {{ dotfiles_dir }} || exit 1
    rc=0
    unit_args=(--tags "{{ tags }}")
    needs_secrets=0
    IFS=',' read -ra tag_list <<< "{{ tags }}"
    for tag in "${tag_list[@]}"; do
      case "$tag" in {{ _secret_tag_pattern }}) needs_secrets=1 ;; esac
    done
    if [ "$needs_secrets" -eq 1 ]; then
      if [ -n "${BW_SESSION:-}" ] && ! bw unlock --check >/dev/null 2>&1; then unset BW_SESSION; fi
      if bw_env=$(scripts/bw-resolve.sh local) && eval "$bw_env" &&
         [ -n "${BW_SESSION:-}" ] && bw unlock --check >/dev/null 2>&1 &&
         timeout 15 bw sync >/dev/null; then
        :
      else
        echo "Bitwarden unavailable or sync failed; skipping secrets." >&2
        unset BW_SESSION
        unit_args+=(--no-secrets)
        rc=1
      fi
    fi
    urc=0; scripts/run-units.sh "${unit_args[@]}" || urc=$?
    [ "$rc" -ne 0 ] || rc=$urc
    scripts/record-apply.py "$rc" apply-tags "{{ tags }}"
    exit "$rc"

# Apply without unlocking Bitwarden — fast path for the daily timer and `dots`
apply-nosecrets *args:
    #!/usr/bin/env bash
    set -uo pipefail
    cd {{ dotfiles_dir }} || exit 1
    git pull --ff-only || true
    for arg in {{ args }}; do
      case "$arg" in --upgrade) export DOTFILES_UPGRADE=1 ;; *) echo "Unknown apply option: $arg" >&2; exit 2 ;; esac
    done
    rc=0; scripts/run-units.sh --no-secrets || rc=$?
    scripts/record-apply.py "$rc" apply-nosecrets secrets
    exit "$rc"

# Apply to a remote machine with specific tags (e.g. just apply-remote-tags bihar kube,shell)
apply-remote-tags name tags:
    #!/usr/bin/env bash
    set -euo pipefail
    # Resolve on the target only for explicitly secret-bearing tags.
    REMOTE_BW_SESSION=""
    IFS=',' read -ra tag_list <<< "{{ tags }}"
    for tag in "${tag_list[@]}"; do
      case "$tag" in
        {{ _secret_tag_pattern }})
          REMOTE_BW_SESSION=$({{ dotfiles_dir }}/scripts/bw-resolve.sh remote {{ name }} || true)
          break ;;
      esac
    done
    EXPECT_SESSION=0; [ -z "$REMOTE_BW_SESSION" ] || EXPECT_SESSION=1
    BW_SESSION="$REMOTE_BW_SESSION" ssh -o SendEnv=BW_SESSION -t {{ name }} "
      export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
      if [ '$EXPECT_SESSION' = 1 ] && [ -z \"\${BW_SESSION:-}\" ]; then
        echo 'SSH server did not accept BW_SESSION; remote apply aborted.' >&2; exit 1
      fi
      cd ~/.local/share/dotfiles && git pull --ff-only && just apply-tags {{ tags }}
    "

# Verify (and self-heal) passwordless SSH to all online fleet members
mesh-check:
    cd {{ dotfiles_dir }} && scripts/run-units.sh --tags mesh_check

# Apply only dotfile configs (shell, git, tmux, etc.)
dotfiles:
    cd {{ dotfiles_dir }} && scripts/run-units.sh --tags dotfiles

# Run the bash units (units/*.sh) in parallel via mise, e.g. `just units --tags omp`
units *args:
    cd {{ dotfiles_dir }} && scripts/run-units.sh {{ args }}

# Apply only packages (Homebrew + Flatpak)
packages:
    cd {{ dotfiles_dir }} && scripts/run-units.sh --tags packages

# Apply to a remote machine, forwarding your local BW session over SSH
apply-remote name *args:
    #!/usr/bin/env bash
    set -euo pipefail
    APPLY_BW_SESSION=$(scripts/bw-resolve.sh remote {{ name }} 2>/dev/null || true)
    if [ -z "$APPLY_BW_SESSION" ]; then
      echo "WARNING: Could not unlock BW on {{ name }}. Continuing without secrets..."
    else
      echo "Bitwarden unlocked on {{ name }} (session: ${#APPLY_BW_SESSION} chars)"
    fi
    echo "Applying to {{ name }} with forwarded BW session..."
    EXPECT_SESSION=0; [ -z "$APPLY_BW_SESSION" ] || EXPECT_SESSION=1
    BW_SESSION="$APPLY_BW_SESSION" ssh -o SendEnv=BW_SESSION -t {{ name }} "
      export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
      if [ '$EXPECT_SESSION' = 1 ] && [ -z \"\${BW_SESSION:-}\" ]; then
        echo 'SSH server did not accept BW_SESSION; remote apply aborted.' >&2; exit 1
      fi
      if [ -n \"\${BW_SESSION:-}\" ]; then
        python3 -c '
    import os, tempfile
    path = \"/tmp/bw_session\"
    fd, temp = tempfile.mkstemp(prefix=\".bw_session.\", dir=\"/tmp\")
    try:
        with os.fdopen(fd, \"w\") as f:
            f.write(os.environ[\"BW_SESSION\"])
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    ' || exit 1
      fi
      cd ~/.local/share/dotfiles && git pull --ff-only && just apply {{ args }}
    "
    just push-terminfo {{ name }}

# Purge a machine from inventory + host_vars, then commit + push
# Usage: just purge <name>
# Does NOT delete the machine's BW items (SSH key, tailscale key) — that's manual.
purge name:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}
    git pull --ff-only
    python3 scripts/purge-machine.py {{ name }} inventory.yml
    git add -A inventory.yml host_vars/
    git diff --cached --quiet || git commit -m "inventory: remove {{ name }}"
    git push

# Register a new machine in inventory and print bootstrap instructions

# Usage: just onboard <name> [desktop|server|vps]
onboard name type="desktop":
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}
    git pull --ff-only

    python3 scripts/register-machine.py {{ name }} {{ type }} inventory.yml

    if [ ! -f "host_vars/{{ name }}.yml" ]; then
      echo "---" > "host_vars/{{ name }}.yml"
    fi

    git add inventory.yml host_vars/{{ name }}.yml
    git diff --cached --quiet || git commit -m "inventory: add {{ name }} ({{ type }})"
    git push

    echo ""
    echo "Bootstrap the new machine by running this on it:"
    echo ""
    echo "  curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name {{ name }}"
    echo ""
    echo "Or if it's already reachable over Tailscale:"
    echo "  just add-machine {{ name }}"
    echo ""
    echo "First get it on the tailnet by scanning a QR with your phone (run ON it):"
    echo "  just tailscale-qr {{ name }}"

# Phase-0 bootstrap-of-trust with NO auth key and NO Bitwarden: runs interactive
# `tailscale up` and renders the login URL as a QR; scan it with your phone and
# approve the device in the Tailscale admin (passwordless via your IdP). Once on
# the tailnet, the machine's identity is its first credential and the rest of
# onboarding (secrets + apply) flows from there. Run ON the new machine; uses
# sudo (interactive onboarding, not the timer). Requires you to be a tagOwner of
# tag:fleet in the ACL; drop --advertise-tags to join as a personal device.
# Details: docs/src/qr-onboarding.md
# Join this machine to the tailnet by scanning a QR with your phone (Phase 0)
tailscale-qr name=machine:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v tailscale >/dev/null 2>&1; then
      echo "→ Tailscale not found; installing..."
      curl -fsSL https://tailscale.com/install.sh | sh
    fi
    echo ""
    echo "Scan this QR with your phone to authorize '{{ name }}' onto the tailnet."
    echo "Approve the device in the Tailscale admin — no password, no auth key."
    echo ""
    sudo tailscale up --qr \
      --hostname="{{ name }}" \
      --advertise-tags=tag:fleet \
      --accept-routes
    echo ""
    echo "✓ '{{ name }}' is on the tailnet. Next: fetch secrets + apply (just apply / just add-machine)."

# ── secret-broker client (Phase 1, #49) — MANUAL/opt-in, not wired into apply ──
# The broker delivers first secrets over the tailnet, gated on tailnet identity +
# an operator approval. Requires a running broker (see tools/secret-broker). Set
# BROKER_URL to override the default. Docs: docs/src/qr-onboarding.md
broker_url := env("BROKER_URL", "http://secret-broker:8080")

# On the NEW node: request secrets from the broker (prints status + fingerprint).
broker-request:
    #!/usr/bin/env bash
    set -uo pipefail
    echo "Requesting secrets from {{ broker_url }} (tailnet identity authenticates me)..."
    curl -sS -w '\nHTTP %{http_code}\n' {{ broker_url }}/v1/secrets

# On your ADMIN node: list nodes awaiting approval (stableID + hostname + fingerprint).
broker-pending:
    #!/usr/bin/env bash
    set -uo pipefail
    curl -sS {{ broker_url }}/v1/admin/pending

# On your ADMIN node: approve a specific StableID (verify its fingerprint first).
broker-approve id:
    #!/usr/bin/env bash
    set -uo pipefail
    curl -sS -X POST "{{ broker_url }}/v1/admin/approve?id={{ id }}" -w '\nHTTP %{http_code}\n'

# Print this node's own Tailscale StableID (compare against the pending list).
broker-myid:
    @tailscale status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['Self']['ID'])"

# Ask the broker what identity + fingerprint it sees for this node (no approval needed).
broker-whoami:
    #!/usr/bin/env bash
    set -uo pipefail
    curl -sS {{ broker_url }}/v1/whoami

# Apply to ALL online fleet machines in parallel (auto-detected via Tailscale)
apply-all:
    #!/usr/bin/env bash
    set -euo pipefail
    ONLINE_HOSTS="{{ _online_hosts }}"
    echo "Online fleet hosts: ${ONLINE_HOSTS:-none}"
    [ -z "$ONLINE_HOSTS" ] && echo "No remote hosts online." && exit 0

    # Resolve a remote-side BW session per host up front (may prompt), since a
    # session is only valid on the machine that unlocked it.
    declare -A SESSIONS
    for host in $ONLINE_HOSTS; do
      SESSIONS[$host]=$(scripts/bw-resolve.sh remote "$host" || true)
    done

    PIDS=()

    echo "Applying locally to {{ machine }}..."
    just apply &
    PIDS+=("$!:{{ machine }}")

    for host in $ONLINE_HOSTS; do
      echo "Applying to $host (background)..."
      ssh "$host" "
        export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
        export BW_SESSION='${SESSIONS[$host]}'
        [ -n \"\$BW_SESSION\" ] && (umask 077 && printf '%s' \"\$BW_SESSION\" > /tmp/bw_session)
        cd ~/.local/share/dotfiles && git pull --ff-only && just apply
      " > "/tmp/apply_${host}.log" 2>&1 &
      PIDS+=("$!:$host")
    done

    echo ""
    echo "Waiting for all hosts to finish..."
    FAILED=()
    for pid_host in "${PIDS[@]}"; do
      pid="${pid_host%%:*}"
      host="${pid_host##*:}"
      if wait "$pid"; then
        echo "  ✓ $host"
      else
        echo "  ✗ $host (see /tmp/apply_${host}.log)"
        FAILED+=("$host")
      fi
    done

    if [ ${#FAILED[@]} -gt 0 ]; then
      echo ""
      echo "Failed hosts: ${FAILED[*]}"
      for host in "${FAILED[@]}"; do
        [ -f "/tmp/apply_${host}.log" ] && echo "=== $host ===" && tail -20 "/tmp/apply_${host}.log"
      done
      exit 1
    fi
    echo "All hosts done ✓"
    just push-terminfo

# Apply specific tags to ALL online fleet machines in parallel
apply-online-tags tags:
    #!/usr/bin/env bash
    set -euo pipefail
    ONLINE_HOSTS="{{ _online_hosts }}"
    echo "Online fleet hosts: ${ONLINE_HOSTS:-none}"
    [ -z "$ONLINE_HOSTS" ] && echo "No remote hosts online." && exit 0

    declare -A SESSIONS
    IFS=',' read -ra tag_list <<< "{{ tags }}"
    for tag in "${tag_list[@]}"; do
      case "$tag" in
        {{ _secret_tag_pattern }})
          for host in $ONLINE_HOSTS; do
            SESSIONS[$host]=$(scripts/bw-resolve.sh remote "$host" || true)
          done
          break ;;
      esac
    done

    PIDS=()

    echo "Applying tags '{{ tags }}' locally to {{ machine }}..."
    just apply-tags {{ tags }} &
    PIDS+=("$!:{{ machine }}")

    for host in $ONLINE_HOSTS; do
      echo "Applying tags '{{ tags }}' to $host (background)..."
      ssh "$host" "
        export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
        export BW_SESSION='${SESSIONS[$host]:-}'
        cd ~/.local/share/dotfiles && git pull --ff-only && just apply-tags {{ tags }}
      " > "/tmp/apply_${host}.log" 2>&1 &
      PIDS+=("$!:$host")
    done

    FAILED=()
    for pid_host in "${PIDS[@]}"; do
      pid="${pid_host%%:*}"
      host="${pid_host##*:}"
      if wait "$pid"; then echo "  ✓ $host"; else echo "  ✗ $host"; FAILED+=("$host"); fi
    done

    [ ${#FAILED[@]} -gt 0 ] && echo "Failed: ${FAILED[*]}" && exit 1
    echo "All hosts done ✓"

# Push local terminal's terminfo to one or all online fleet hosts
# Usage: just push-terminfo [host]  — omit host to push to all online hosts
push-terminfo host="":
    #!/usr/bin/env bash
    set -euo pipefail
    TARGETS="{{ host }}"
    if [ -z "$TARGETS" ]; then
      TARGETS="{{ _online_hosts }}"
    fi
    [ -z "$TARGETS" ] && echo "No hosts to push terminfo to." && exit 0
    for h in $TARGETS; do
      echo "Pushing $TERM terminfo to $h..."
      infocmp -x | ssh "$h" -- tic -x - && echo "  ✓ $h" || echo "  ✗ $h (tic failed)"
    done

# Show which fleet machines are currently online via Tailscale
online:
    @echo "Online fleet hosts: {{ _online_hosts }}"

# Bootstrap a new machine over SSH — registers it in inventory then runs bootstrap.sh
# Usage: just add-machine kerala             (defaults to desktop)
#        just add-machine kerala server
add-machine name type="desktop":
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}
    git pull --ff-only

    # Register in inventory if not already present
    if ! grep -q "^    {{ name }}:" inventory.yml 2>/dev/null; then
      echo "→ Registering {{ name }} ({{ type }}) in inventory..."
      python3 scripts/register-machine.py {{ name }} {{ type }} inventory.yml
      if [ ! -f "host_vars/{{ name }}.yml" ]; then
        echo "---" > "host_vars/{{ name }}.yml"
      fi
      git add inventory.yml "host_vars/{{ name }}.yml"
      git diff --cached --quiet || git commit -m "inventory: add {{ name }} ({{ type }})"
      git push
      echo "✓ Inventory updated and pushed."
    else
      echo "✓ {{ name }} already in inventory."
    fi

    # Bootstrap on the remote machine.
    # -t allocates a PTY so /dev/tty is available for any remaining prompts.
    echo "→ Bootstrapping {{ name }}..."
    ssh -t {{ name }} \
      "curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
       | bash -s -- --name {{ name }} --type {{ type }}"

# Pull latest changes and apply
update *args:
    cd {{ dotfiles_dir }} && git pull --ff-only && just apply {{ args }}

# Pull latest, apply, and upgrade all packages
update-all:
    just update --upgrade

# Sync current Homebrew state back to dotfiles variables
sync-brews:
    #!/usr/bin/env bash
    set -euo pipefail
    ./scripts/sync-brews.sh
    git diff group_vars/all.yml

# Install a flatpak system-wide and persist it to dotfiles
flatpak-install app:
    #!/usr/bin/env bash
    set -euo pipefail
    flatpak install --system -y flathub {{ app }}
    cd {{ dotfiles_dir }}
    yq -i '.system_flatpaks += ["{{ app }}"]' units/flatpak-packages.yml
    git add units/flatpak-packages.yml
    git commit -m "flatpak: add {{ app }}"
    git push

# Edit this machine's host_vars
edit-host:
    ${EDITOR:-vi} {{ dotfiles_dir }}/host_vars/{{ machine }}.yml

# Update all neovim plugins (headless)
nvim-update:
    nvim --headless "+Lazy! sync" +qa

# Open neovim (alias for muscle memory)
vim *args:
    nvim {{ args }}

# Lint YAML and check native unit shell syntax
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}
    rc=0
    if command -v yamllint >/dev/null 2>&1; then
      echo "→ yamllint"
      yamllint -d "{extends: default, rules: {line-length: disable, document-start: disable, truthy: disable, comments-indentation: disable, indentation: disable, braces: disable, empty-lines: disable, commas: disable, comments: disable}}" . || rc=$?
    else
      echo "yamllint not installed (brew install yamllint) — skipping"
    fi
    for file in bootstrap.sh scripts/run-units.sh units/*.sh; do
      bash -n "$file" || rc=$?
    done
    exit $rc

# Inspect native configuration without applying changes
check *args:
    cd {{ dotfiles_dir }} && UNITS_CHECK=1 scripts/run-units.sh {{ args }}

# Log omp into all providers (OAuth prompts only for missing ones)
omp-login:
    {{ dotfiles_dir }}/scripts/omp-login.sh

# Smoke-test omp providers and show remaining quota (ccleft)
omp-test:
    {{ dotfiles_dir }}/scripts/omp-test.sh

# Health check: verify this machine is in a good state
doctor:
    #!/usr/bin/env bash
    set -uo pipefail
    cd {{ dotfiles_dir }}
    fail=0
    pass() { printf '  ✓ %s\n' "$1"; }
    warn() { printf '  ⚠ %s\n' "$1"; fail=1; }
    echo "→ Machine identity"
    if [ -f /etc/dotfiles-machine ]; then pass "machine: $(cat /etc/dotfiles-machine)"; else warn "/etc/dotfiles-machine missing — run bootstrap"; fi
    echo "→ Core binaries"
    for bin in brew bw gh tailscale just mise chezmoi yq python3; do
      if command -v "$bin" >/dev/null 2>&1; then pass "$bin"; else warn "$bin missing"; fi
    done
    echo "→ Tailscale"
    if tailscale status >/dev/null 2>&1; then pass "connected"; else warn "not connected to tailnet"; fi
    echo "→ Bitwarden"
    bw_status=$(bw status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
    case "$bw_status" in
      unlocked) pass "vault unlocked" ;;
      locked)   warn "vault locked — run: export BW_SESSION=\$(bw unlock --raw)" ;;
      *)        warn "vault status: $bw_status" ;;
    esac
    echo "→ GitHub auth"
    if gh auth status >/dev/null 2>&1; then pass "gh authenticated"; else warn "gh not authenticated"; fi
    echo "→ SSH key"
    if [ -f ~/.ssh/id_ed25519 ]; then pass "id_ed25519 present"; else warn "no ~/.ssh/id_ed25519"; fi
    echo "→ Dotfiles repo"
    if git -C {{ dotfiles_dir }} diff --quiet && git -C {{ dotfiles_dir }} diff --cached --quiet; then
      pass "clean working tree"
    else
      warn "uncommitted changes in {{ dotfiles_dir }}"
    fi
    if [ "$(git -C {{ dotfiles_dir }} rev-list HEAD..@{u} --count 2>/dev/null || echo 0)" -gt 0 ]; then
      warn "local branch behind upstream — run: just update"
    else
      pass "up to date with upstream"
    fi
    echo "→ Systemd timers"
    if systemctl --user is-active dotfiles-update.timer >/dev/null 2>&1 || systemctl --user is-active dotfiles-update.service >/dev/null 2>&1; then
      pass "dotfiles-update unit active"
    else
      warn "dotfiles-update timer/service not active"
    fi
    echo "→ Last apply"
    if [ -s ~/.cache/dotfiles/last-apply.json ]; then
      if ! python3 {{ dotfiles_dir }}/scripts/last-apply-status.py; then
        fail=1
      fi
    else
      warn "no apply has been recorded yet — run: just apply"
    fi
    exit $fail

# Inventory the local LAN with nmap + Tailscale (no NetBox required)
# Usage: just inventory               (defaults to 192.168.0.0/24)
#        just inventory 10.0.0.0/24
inventory subnet="192.168.0.0/24":
    @{{ dotfiles_dir }}/scripts/nmap-inventory.sh {{ subnet }}

# Serve the docs/ mdbook locally with live reload (Ctrl+C to stop)
docs:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v mdbook >/dev/null; then
      echo "mdbook not installed — brew install mdbook" >&2
      exit 1
    fi
    cd {{ dotfiles_dir }}/docs && mdbook serve --open

# Build the docs into target/book/ as static HTML
docs-build:
    #!/usr/bin/env bash
    set -euo pipefail
    if ! command -v mdbook >/dev/null; then
      echo "mdbook not installed — brew install mdbook" >&2
      exit 1
    fi
    cd {{ dotfiles_dir }}/docs && mdbook build

# Seed Bitwarden with this machine's kubeconfig + talosconfig (so other machines can fetch)
seed-kube:
    @{{ dotfiles_dir }}/scripts/bw-seed-kube.sh

# Seed Bitwarden with the omp auth-broker token via SSH to spindle
seed-omp-broker:
    @{{ dotfiles_dir }}/scripts/bw-seed-omp-broker.sh

# Tailnet hygiene (scripts/tailnet.py): audit is read-only; the others dry-run unless `--apply`
tailnet-audit:
    @{{ dotfiles_dir }}/scripts/tailnet.py audit

# gc + rename + inventory alignment, e.g. `just tailnet-sync --apply`
tailnet-sync *args:
    @{{ dotfiles_dir }}/scripts/tailnet.py sync {{ args }}

# Store the Tailscale OAuth client secret (device gc/rename + join key) in Bitwarden
seed-tailnet-oauth:
    @{{ dotfiles_dir }}/scripts/bw-seed-tailnet.sh

# Show all online fleet machines' doctor status in parallel
doctor-fleet:
    #!/usr/bin/env bash
    set -uo pipefail
    ONLINE_HOSTS="{{ _online_hosts }}"
    just doctor || true
    for h in $ONLINE_HOSTS; do
      echo ""
      echo "═══ $h ═══"
      ssh -o BatchMode=yes "$h" 'cd ~/.local/share/dotfiles && just doctor' || true
    done

# Private osquery drift and explicit online/offline/unsupported coverage.
osquery-fleet *args:
    python3 "{{justfile_directory()}}/scripts/osquery-fleet.py" {{args}}

# Build a shared starter or configured home-node image; never touches a physical disk.
server-image node tag="testing":
    #!/usr/bin/env bash
    set -euo pipefail
    node={{quote(node)}}
    tag={{quote(tag)}}
    case "$node" in starter|bihar|karnataka) ;; *) echo "Expected starter, bihar or karnataka" >&2; exit 2 ;; esac
    revision=$(git -C "{{justfile_directory()}}" rev-parse HEAD)
    podman build --no-hostname --target "$node" --tag "localhost/home-k8s-$node:$tag" \
      --label "org.opencontainers.image.revision=$revision" \
      --file "{{justfile_directory()}}/server-images/Containerfile" "{{justfile_directory()}}/server-images"

# Build the starter and both home variants from the same base and Kubernetes release.
server-images tag="testing":
    just server-image starter {{quote(tag)}}
    just server-image bihar {{quote(tag)}}
    just server-image karnataka {{quote(tag)}}

# Build UEFI live media with bootc-installer-tui and this node's offline payload.
server-installer node target_ref output tag="testing":
    "{{justfile_directory()}}/server-images/build-installer.sh" {{quote(node)}} {{quote(target_ref)}} {{quote(output)}} {{quote(tag)}}

# ── AWS account IaC (aws/, OpenTofu) ─────────────────────────────────────
# Docs: docs/src/servers/aws/README.md. Needs AWS creds (`aws login`) and
# aws/terraform.tfvars, which holds personal IPs + alert address and so lives in
# the Bitwarden note `aws-tofu-tfvars`, not in git.

# Fetch aws/terraform.tfvars from Bitwarden (no-op if it already exists)
aws-tfvars:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}/aws
    [ -f terraform.tfvars ] && exit 0
    eval "$({{ dotfiles_dir }}/scripts/bw-resolve.sh local)"
    (umask 077 && bw get notes aws-tofu-tfvars > terraform.tfvars)
    echo "✓ aws/terraform.tfvars fetched from Bitwarden"

# Push aws/terraform.tfvars to the Bitwarden note `aws-tofu-tfvars` (create or update)
aws-seed-tfvars:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}/aws
    eval "$({{ dotfiles_dir }}/scripts/bw-resolve.sh local)"
    bw sync >/dev/null
    id=$(bw get item aws-tofu-tfvars 2>/dev/null | jq -r .id || true)
    if [ -n "$id" ]; then
      bw get item "$id" | jq --rawfile n terraform.tfvars '.notes=$n' | bw encode | bw edit item "$id" >/dev/null
    else
      bw get template item | jq --rawfile n terraform.tfvars \
        '.type=2 | .secureNote={type:0} | .name="aws-tofu-tfvars" | .notes=$n' \
        | bw encode | bw create item >/dev/null
    fi
    echo "✓ aws-tofu-tfvars saved to Bitwarden"

# Show what OpenTofu would change in the AWS account (read-only)
aws-plan *args: aws-tfvars
    cd {{ dotfiles_dir }}/aws && tofu init -input=false >/dev/null && tofu plan {{ args }}

# Apply the AWS IaC (interactive confirmation; prevent_destroy guards the nodes)
aws-apply *args: aws-tfvars
    cd {{ dotfiles_dir }}/aws && tofu init -input=false >/dev/null && tofu apply {{ args }}
