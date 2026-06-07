# Dotfiles management with Ansible
# Usage: just <recipe>

dotfiles_dir := env("HOME") / ".local/share/dotfiles"
machine := `cat /etc/dotfiles-machine 2>/dev/null || hostname`
export PATH := env("HOME") / ".local/bin" + ":/home/linuxbrew/.linuxbrew/bin:" + env("PATH")

# Resolve online fleet hosts: intersect tailscale online peers with inventory (excluding vps + self)
_online_hosts := ```
python3 -c "
import subprocess, json, re, os
ts = json.loads(subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True).stdout)
online = set()
for p in ts.get('Peer', {}).values():
    if p.get('Online'):
        online.add(p.get('DNSName', '').lower().split('.')[0])
        online.add(p.get('HostName', '').lower())
inv_path = os.path.expanduser('~/.local/share/dotfiles/inventory.yml')
raw = open(inv_path).read()
# Parse hosts from inventory.yml without PyYAML — extract 'hostname:' keys under 'hosts:'
all_hosts = set(re.findall(r'^\s{4}(\w+):\s*$', raw, re.MULTILINE))
vps = set(re.findall(r'^\s{6}(\w+):\s*$', raw, re.MULTILINE))
all_hosts -= vps | {os.uname().nodename.lower()}
print(' '.join(sorted(all_hosts & online)))
"
```

# Apply all config to this machine (unlocks BW interactively if needed)
apply *args:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}
    git pull --ff-only
    ansible-galaxy collection install -r requirements.yml

    BECOME_ARGS=""
    if ! sudo -n true 2>/dev/null; then
      echo "Sudo requires a password. Adding --ask-become-pass..."
      BECOME_ARGS="--ask-become-pass"
    fi

    # Tries env → /tmp cache → interactive unlock. Exits 3 if BW isn't logged
    # in on this machine and 4 if the user declined to unlock; both should
    # silently fall through to a no-secrets apply.
    SKIP_TAGS=""
    if [ -z "${BW_SESSION:-}" ]; then
      if BW_SESSION_OUT=$(scripts/bw-unlock.sh 2>/dev/null); then
        export BW_SESSION="$BW_SESSION_OUT"
      else
        echo "Continuing without secrets (run scripts/bw-unlock.sh manually for details)..."
        SKIP_TAGS="secrets"
      fi
    fi
    rc=0
    if [ -n "$SKIP_TAGS" ]; then
      ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 site.yml --skip-tags "$SKIP_TAGS" $BECOME_ARGS {{ args }} || rc=$?
    else
      ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 -e "bw_session=${BW_SESSION:-}" site.yml $BECOME_ARGS {{ args }} || rc=$?
    fi
    scripts/record-apply.py "$rc" apply "$SKIP_TAGS"
    exit $rc

# Apply only specific tags (e.g. just apply-tags homepage,proxy)
apply-tags tags:
    #!/usr/bin/env bash
    set -uo pipefail
    cd {{ dotfiles_dir }}
    rc=0
    ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 -e "bw_session=${BW_SESSION:-}" site.yml --tags {{ tags }} || rc=$?
    scripts/record-apply.py "$rc" apply-tags "{{ tags }}"
    exit $rc

# Apply without unlocking Bitwarden — fast path for the daily timer and `dots`
apply-nosecrets *args:
    #!/usr/bin/env bash
    set -uo pipefail
    cd {{ dotfiles_dir }}
    git pull --ff-only || true
    rc=0
    ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 site.yml --skip-tags secrets {{ args }} || rc=$?
    scripts/record-apply.py "$rc" apply-nosecrets secrets
    exit $rc

# Apply to a remote machine with specific tags (e.g. just apply-remote-tags bihar homepage,proxy)
apply-remote-tags name tags:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "${BW_SESSION:-}" ]; then
      export BW_SESSION=$({{ dotfiles_dir }}/scripts/bw-unlock.sh)
    fi
    ssh -t {{ name }} "
      export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
      export BW_SESSION='${BW_SESSION}'
      cd ~/.local/share/dotfiles && git pull --ff-only && just apply-tags {{ tags }}
    "

# Apply only dotfile configs (shell, git, tmux, etc.)
dotfiles:
    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 site.yml --tags dotfiles

# Apply only packages (Homebrew + Flatpak)
packages:
    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 site.yml --tags packages

# Apply to a remote machine, forwarding your local BW session over SSH
apply-remote name *args:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "${BW_SESSION:-}" ]; then
      export BW_SESSION=$({{ dotfiles_dir }}/scripts/bw-unlock.sh)
    fi
    # Ensure bw is logged in on the remote — BW_SESSION is only an unlock token,
    # it requires a prior 'bw login' on that machine. If unauthenticated, try
    # to login via API key (fetched from local vault as 'bw-api-key' item).
    REMOTE_STATUS=$(ssh {{ name }} '/home/linuxbrew/.linuxbrew/bin/bw status 2>/dev/null || echo "{}"')
    if echo "$REMOTE_STATUS" | grep -q '"unauthenticated"'; then
      echo "Bitwarden not logged in on {{ name }}. Attempting API key login..."
      BW_CLIENTID=$(bw get username bw-api-key --session "$BW_SESSION" 2>/dev/null || true)
      BW_CLIENTSECRET=$(bw get password bw-api-key --session "$BW_SESSION" 2>/dev/null || true)
      if [ -n "$BW_CLIENTID" ] && [ -n "$BW_CLIENTSECRET" ]; then
        # Interpolate credentials directly — avoids AcceptEnv dependency
        ssh {{ name }} "
          export PATH='/home/linuxbrew/.linuxbrew/bin:\$PATH'
          export BW_CLIENTID='${BW_CLIENTID}'
          export BW_CLIENTSECRET='${BW_CLIENTSECRET}'
          bw login --apikey 2>&1 || true
        "
        echo "BW login done on {{ name }}."
      else
        echo "WARNING: No 'bw-api-key' item in vault. Run 'bw login' on {{ name }} manually, then re-run."
        echo "  ssh {{ name }} 'bw login'"
      fi
    fi
    # BW_SESSION from this machine can't decrypt the remote vault — unlock BW
    # on the remote using its own master password, and use that session instead.
    # Try fetching master password from local vault first (non-interactive).
    REMOTE_BW_SESSION=""
    if echo "$REMOTE_STATUS" | grep -qE '"locked"|"unauthenticated"'; then
      BW_MASTER_PASS=$(bw get password "James Bitwarden" --session "$BW_SESSION" 2>/dev/null || true)
      if [ -n "$BW_MASTER_PASS" ]; then
        echo "Unlocking Bitwarden on {{ name }} (non-interactive)..."
        REMOTE_BW_SESSION=$(ssh {{ name }} \
          "export PATH='/home/linuxbrew/.linuxbrew/bin:\$PATH'; BW_PASSWORD='${BW_MASTER_PASS}' bw unlock --passwordenv BW_PASSWORD --raw 2>/dev/null" \
          | tr -d '\r\n')
        if [ -z "$REMOTE_BW_SESSION" ]; then
          echo "  passwordenv failed, trying positional arg..."
          REMOTE_BW_SESSION=$(ssh {{ name }} \
            "export PATH='/home/linuxbrew/.linuxbrew/bin:\$PATH'; bw unlock --raw '${BW_MASTER_PASS}' 2>/dev/null" \
            | tr -d '\r\n')
        fi
      fi
      if [ -z "$REMOTE_BW_SESSION" ]; then
        echo "Unlocking Bitwarden on {{ name }} (enter master password when prompted)..."
        REMOTE_BW_SESSION=$(ssh -t {{ name }} \
          'export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"; bw unlock --raw 2>/dev/null' \
          | tr -d '\r\n')
      fi
      if [ -z "$REMOTE_BW_SESSION" ]; then
        echo "WARNING: Could not unlock BW on {{ name }}. Continuing without secrets..."
      else
        echo "Bitwarden unlocked on {{ name }} (session: ${#REMOTE_BW_SESSION} chars)"
      fi
    fi
    # Use remote's own session if we got one, otherwise fall back to local
    APPLY_BW_SESSION="${REMOTE_BW_SESSION:-$BW_SESSION}"
    echo "Applying to {{ name }} with forwarded BW session..."
    # Interpolate BW_SESSION directly — avoids AcceptEnv dependency on fresh machines
    ssh -t {{ name }} "
      export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
      export BW_SESSION='${APPLY_BW_SESSION}'
      (umask 077 && printf '%s' \"\$BW_SESSION\" > /tmp/bw_session)
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
    git add inventory.yml "host_vars/{{ name }}.yml" 2>/dev/null || true
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
      echo "is_arm: false" > "host_vars/{{ name }}.yml"
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

# Apply to ALL online fleet machines in parallel (auto-detected via Tailscale)
apply-all:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "${BW_SESSION:-}" ]; then
      if [ -f /tmp/bw_session ]; then
        export BW_SESSION=$(cat /tmp/bw_session)
      else
        echo "Unlocking Bitwarden..."
        export BW_SESSION=$(bw unlock --raw)
        (umask 077 && printf '%s' "$BW_SESSION" > /tmp/bw_session)
      fi
    fi

    ONLINE_HOSTS="{{ _online_hosts }}"
    echo "Online fleet hosts: ${ONLINE_HOSTS:-none}"
    [ -z "$ONLINE_HOSTS" ] && echo "No remote hosts online." && exit 0

    PIDS=()

    echo "Applying locally to {{ machine }}..."
    just apply &
    PIDS+=("$!:{{ machine }}")

    for host in $ONLINE_HOSTS; do
      echo "Applying to $host (background)..."
      ssh "$host" "
        export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
        export BW_SESSION='${BW_SESSION}'
        (umask 077 && printf '%s' \"\$BW_SESSION\" > /tmp/bw_session)
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
    if [ -z "${BW_SESSION:-}" ]; then
      [ -f /tmp/bw_session ] && export BW_SESSION=$(cat /tmp/bw_session) || export BW_SESSION=$(bw unlock --raw)
    fi

    ONLINE_HOSTS="{{ _online_hosts }}"
    echo "Online fleet hosts: ${ONLINE_HOSTS:-none}"
    [ -z "$ONLINE_HOSTS" ] && echo "No remote hosts online." && exit 0

    PIDS=()

    echo "Applying tags '{{ tags }}' locally to {{ machine }}..."
    just apply-tags {{ tags }} &
    PIDS+=("$!:{{ machine }}")

    for host in $ONLINE_HOSTS; do
      echo "Applying tags '{{ tags }}' to $host (background)..."
      ssh "$host" "
        export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
        export BW_SESSION='${BW_SESSION}'
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
        echo "is_arm: false" > "host_vars/{{ name }}.yml"
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
update:
    cd {{ dotfiles_dir }} && git pull --ff-only && just apply

# Pull latest, apply, and upgrade all packages
update-all:
    just update -e upgrade=true

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
    yq -i '.system_flatpaks += ["{{ app }}"]' group_vars/all.yml
    git add group_vars/all.yml
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

# Lint YAML + Ansible playbook (uses tools from Brewfile when available)
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
    if command -v ansible-lint >/dev/null 2>&1; then
      echo "→ ansible-lint"
      ansible-lint site.yml || rc=$?
    else
      echo "ansible-lint not installed (uv tool install ansible-lint) — skipping"
    fi
    exit $rc

# Dry-run apply (no changes) — quick way to see what would change
check *args:
    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e ansible_connection=local -e ansible_host=127.0.0.1 site.yml --check --diff {{ args }}

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
    for bin in brew bw gh tailscale ansible-playbook just; do
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
