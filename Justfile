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
        export BW_SESSION=$(bw unlock --raw)
        echo "$BW_SESSION" > /tmp/bw_session
        chmod 600 /tmp/bw_session
      fi
    fi
    ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml

# Apply without secrets
apply-nosecrets:
    cd {{dotfiles_dir}} && git pull --ff-only && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --skip-tags secrets

# Apply only dotfile configs (shell, git, tmux, etc.)
dotfiles:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --tags dotfiles

# Apply only packages (Homebrew + Flatpak)
packages:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --tags packages

# Add a new machine (run from your main machine with BW unlocked)
add-machine name:
    ssh -o SendEnv=BW_SESSION james@{{name}} 'curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash -s -- --name {{name}}'

# Pull latest changes and apply
update:
    cd {{dotfiles_dir}} && git pull --ff-only && just apply

# Check what would change (dry run)
check:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --check --diff

# Edit this machine's host_vars
edit-host:
    ${EDITOR:-vi} {{dotfiles_dir}}/host_vars/{{machine}}.yml
