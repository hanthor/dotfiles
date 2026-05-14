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
    ansible-galaxy install -r requirements.yml
    if [ -z "${BW_SESSION:-}" ]; then
      if [ -f /tmp/bw_session ]; then
        export BW_SESSION=$(cat /tmp/bw_session)
      else
        BW_STATUS=$(bw status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
        if [ "$BW_STATUS" = "unauthenticated" ]; then
          echo "WARNING: Bitwarden not logged in on this machine."
          echo "  Run 'just apply-remote {{ machine }}' from karnataka, or run 'bw login' manually first."
          echo "Continuing without secrets..."
          exec ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} site.yml --skip-tags secrets {{ args }}
        fi
        echo "Unlocking Bitwarden..."
        if ! export BW_SESSION=$(bw unlock --raw 2>/dev/null); then
          echo "WARNING: Bitwarden unlock failed. Continuing without secrets..."
          exec ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} site.yml --skip-tags secrets {{ args }}
        fi
        echo "$BW_SESSION" > /tmp/bw_session
        chmod 600 /tmp/bw_session
      fi
    fi
    ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e "bw_session=${BW_SESSION:-}" site.yml {{ args }}

# Apply only specific tags (e.g. just apply-tags homepage,proxy)
apply-tags tags:
    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} -e "bw_session=${BW_SESSION:-}" site.yml --tags {{ tags }}

# Apply to a remote machine with specific tags (e.g. just apply-remote-tags bihar homepage,proxy)
apply-remote-tags name tags:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -z "${BW_SESSION:-}" ]; then
      [ -f /tmp/bw_session ] && export BW_SESSION=$(cat /tmp/bw_session) || export BW_SESSION=$(bw unlock --raw)
    fi
    ssh {{ name }} "
      export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
      export BW_SESSION='${BW_SESSION}'
      cd ~/.local/share/dotfiles && git pull --ff-only && ansible-playbook --connection=local -l {{ name }} -e target={{ name }} -e \"bw_session=${BW_SESSION}\" site.yml --tags {{ tags }}
    "

# Apply only dotfile configs (shell, git, tmux, etc.)
dotfiles:
    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} site.yml --tags dotfiles

# Apply only packages (Homebrew + Flatpak)
packages:
    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} site.yml --tags packages

# Apply to a remote machine, forwarding your local BW session over SSH
apply-remote name *args:
    #!/usr/bin/env bash
    set -euo pipefail
    # ... (skipping some lines for brevity in old_string match)
    # Use remote's own session if we got one, otherwise fall back to local
    APPLY_BW_SESSION="${REMOTE_BW_SESSION:-$BW_SESSION}"
    echo "Applying to {{ name }} with forwarded BW session..."
    # Interpolate BW_SESSION directly — avoids AcceptEnv dependency on fresh machines
    ssh -t {{ name }} "
      export PATH=\"\$HOME/.local/bin:/home/linuxbrew/.linuxbrew/bin:\$PATH\"
      export BW_SESSION='${APPLY_BW_SESSION}'
      echo \"\$BW_SESSION\" > /tmp/bw_session
      chmod 600 /tmp/bw_session
      cd ~/.local/share/dotfiles && git pull --ff-only && just apply {{ args }}
    "
    just push-terminfo {{ name }}

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
        echo "$BW_SESSION" > /tmp/bw_session
        chmod 600 /tmp/bw_session
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
        echo \"\$BW_SESSION\" > /tmp/bw_session && chmod 600 /tmp/bw_session
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

# Add a new machine (run from your main machine with BW unlocked)
add-machine name:
    ssh -o SendEnv=BW_SESSION james@{{ name }} 'curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name {{ name }}'

# Pull latest changes and apply
update:
    cd {{ dotfiles_dir }} && git pull --ff-only && just apply

# Apply to all machines in parallel via Ansible (run from karnataka)

# Unlocks BW locally and passes session via extra-var; uses SSH connection to remotes
apply-ansible:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{ dotfiles_dir }}
    git pull --ff-only
    if [ -z "${BW_SESSION:-}" ]; then
      if [ -f /tmp/bw_session ]; then
        export BW_SESSION=$(cat /tmp/bw_session)
      else
        echo "Unlocking Bitwarden..."
        export BW_SESSION=$(bw unlock --raw)
        echo "$BW_SESSION" > /tmp/bw_session
        chmod 600 /tmp/bw_session
      fi
    fi
    ansible-playbook site.yml \
      --forks 10 \
      -e "bw_session=${BW_SESSION}" \
      -e "target=all" \
      "$@"


    cd {{ dotfiles_dir }} && ansible-playbook --connection=local -l {{ machine }} -e target={{ machine }} site.yml --check --diff

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
