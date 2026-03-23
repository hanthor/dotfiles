# Dotfiles management with Ansible
# Usage: just <recipe>

dotfiles_dir := env("HOME") / ".local/share/dotfiles"
machine := `cat /etc/dotfiles-machine 2>/dev/null || hostname`

# Apply all config to this machine
apply:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml

# Apply without secrets (skip BW-dependent roles)
apply-nosecrets:
    cd {{dotfiles_dir}} && ansible-playbook --connection=local -l {{machine}} -e target={{machine}} site.yml --skip-tags secrets

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
