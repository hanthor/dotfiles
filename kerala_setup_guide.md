# Setting up and applying playbook to kerala machine

## Understanding the issue

Based on the error messages, there are two problems:
1. `sh: just: not found` - The `just` command is not installed or not in PATH on the remote machine
2. `error: justfile does not contain recipe 'kerala'` - This error suggests a misunderstanding in command usage

## Current setup for kerala

Looking at the inventory, kerala is already configured in `inventory.yml` with:
```yaml
all:
  hosts:
    kerala:
      ansible_host: localhost
      ansible_connection: local
```

And in `host_vars/kerala.yml`:
```yaml
---
# ARM hardware
is_arm: true
# Laptop: runs on login, not on timer
is_laptop: true
```

## Recommended approach for applying to kerala

Since kerala is a PostMarketOS machine (Alpine-based), and it's already in the inventory, you have several options:

### Option 1: Direct Ansible execution (from karnataka or any machine with dotfiles)

```bash
# Run directly on the machine where you want to apply (karnataka)
ansible-playbook --connection=local -l kerala site.yml

# Or with specific tags for more granular control
ansible-playbook --connection=local -l kerala site.yml --tags "dotfiles,packages,gnome"
```

### Option 2: Using just apply-remote command (from karnataka)

From karnataka, you should run:
```bash
just apply-remote kerala
```

This command should work if `just` is properly installed on karnataka and properly configured. 

### Option 3: Manual bootstrap if just is not available

If `just` is not available on kerala, you can:

1. Ensure the dotfiles repository is cloned and available on kerala
2. Install `just` on kerala:
   ```bash
   # Using the official install script
   curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash
   ```

3. Then run the playbook:
   ```bash
   just apply
   ```

## Troubleshooting

### If you get "just: not found" on kerala:
```bash
# Install just on kerala
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash
```

### If you get "recipe 'kerala' does not contain recipe 'kerala'":
The correct command is:
```bash
just apply-remote kerala
```

This command should work from karnataka to apply configurations to kerala.

## Testing the configuration

To verify everything works, try:
```bash
# From karnataka
ansible-playbook --connection=local -l kerala site.yml --check
```

This will show what changes would be made without actually applying them.

## Current roles support for kerala

The current configuration supports:
- Desktop setup (is_desktop: true from group_vars/desktop.yml)
- Alpine/PostMarketOS package management via apk_packages role
- All standard dotfiles roles that are compatible with Alpine

## Verification

Check that kerala is properly recognized:
```bash
ansible-inventory -i inventory.yml --list | grep kerala
```