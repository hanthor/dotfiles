# Dotfiles management with Ansible
# Usage: just <recipe>

dotfiles_dir := env("HOME") / ".local/share/dotfiles"
machine := `cat /etc/dotfiles-machine 2>/dev/null || hostname`
export PATH := env("HOME") / ".local/bin" + ":/home/linuxbrew/.linuxbrew/bin:" + env("PATH")

# Apply all config to this machine (unlocks BW interactively if needed)
apply:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{dotfiles_dir}}
    git pull --ff-only
    if [ -z "${BW_SESSION:-}" ]; then
      if [ -f /tmp/bw_session ]; then
        export BW_SESSION=$(cat /tmp/bw_session)
      else
        echo "Unlocking Bitwarden..."
        if ! export BW_SESSION=$(bw unlock --raw 2>/dev/null); then
          echo "WARNING: Bitwarden unlock failed (not logged in?). Run 'bw login' first."
          echo "Continuing without secrets..."
          exec ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --skip-tags secrets
        fi
        echo "$BW_SESSION" > /tmp/bw_session
        chmod 600 /tmp/bw_session
      fi
    fi
    ansible-playbook --connection=local -l {{machine}} -e target={{machine}} -e "bw_session=${BW_SESSION:-}" site.yml

# Apply without secrets
apply-nosecrets:
    cd {{dotfiles_dir}} && git pull --ff-only && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --skip-tags secrets

# Apply only dotfile configs (shell, git, tmux, etc.)
dotfiles:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --tags dotfiles

# Apply only packages (Homebrew + Flatpak)
packages:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --tags packages

# Apply to a remote machine, forwarding your local BW session over SSH
apply-remote name:
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
    echo "Applying to {{name}} with forwarded BW session..."
    ssh -o SendEnv=BW_SESSION {{name}} 'cd ~/.local/share/dotfiles && git pull --ff-only && just apply'

# Apply to ALL remote machines in parallel, forwarding your local BW session
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

    HOSTS=(bihar kanpur lkofoss himachal dilli)
    PIDS=()
    UP=()

    echo "Checking which hosts are reachable..."
    for host in "${HOSTS[@]}"; do
      if ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" true 2>/dev/null; then
        UP+=("$host")
      else
        echo "  ⚠ $host — unreachable, skipping"
      fi
    done

    echo ""
    echo "Applying locally to {{machine}}..."
    just apply &
    PIDS+=("$!:{{machine}}")

    for host in "${UP[@]}"; do
      echo "Applying to $host (background)..."
      ssh -o SendEnv=BW_SESSION "$host" \
        'cd ~/.local/share/dotfiles && git pull --ff-only && just apply' \
        > "/tmp/apply_${host}.log" 2>&1 &
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
        [ -f "/tmp/apply_${host}.log" ] && echo "=== $host ===" && tail -10 "/tmp/apply_${host}.log"
      done
      exit 1
    fi
    echo ""
    echo "All hosts done ✓"

# Add a new machine (run from your main machine with BW unlocked)
add-machine name:
    ssh -o SendEnv=BW_SESSION james@{{name}} 'curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name {{name}}'

# Pull latest changes and apply
update:
    cd {{dotfiles_dir}} && git pull --ff-only && just apply

# Apply to all machines in parallel via Ansible (run from karnataka)
# Unlocks BW locally and passes session via extra-var; uses SSH connection to remotes
apply-ansible:
    #!/usr/bin/env bash
    set -euo pipefail
    cd {{dotfiles_dir}}
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
      -e "target=all"


    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --check --diff

# Install a flatpak system-wide and persist it to dotfiles
flatpak-install app:
    #!/usr/bin/env bash
    set -euo pipefail
    flatpak install --system -y flathub {{app}}
    cd {{dotfiles_dir}}
    yq -i '.system_flatpaks += ["{{app}}"]' group_vars/all.yml
    git add group_vars/all.yml
    git commit -m "flatpak: add {{app}}"
    git push

# Edit this machine's host_vars
edit-host:
    ${EDITOR:-vi} {{dotfiles_dir}}/host_vars/{{machine}}.yml
