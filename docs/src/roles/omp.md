# omp

**Tags:** `dotfiles`, `omp`  
**Secrets needed:** No for OMP/Kiro installation; `shell_ai` optionally provides the DeepSeek API key  
**Runs on:** All supported hosts except raw Termux

Installs Oh My Pi and the Kiro provider on each supported computer. Homebrew hosts install OMP and Bun from the `can1357/tap` tap. musl hosts use OMP's checksum-verified binary installer and Bun's installer. The Kiro provider is installed from `github:elkibalion/omp-kiro-provider`.

## What It Does

1. Installs and verifies `omp`.
2. Installs the Kiro provider plugin for the current user; it is available as `kiro/*` models.
3. Deploys personal skills to `~/.omp/agent/skills/james/` and symlinks them into `~/.claude/skills/`.
4. Exposes the Bitwarden DeepSeek key as `DEEPSEEK_API_KEY` through the shell secret files, not an agent-specific credential file.
5. Removes the legacy Pi CLI from raw Termux. OMP has no native Android/Bionic build; the Debian VM (`mumbai`) is supported normally.

## Skills and the package manifest

The playbook copies `roles/pi/files/skills/` to
`~/.omp/agent/skills/james/` and links those skill directories into
`~/.claude/skills/`. The `roles/pi` path is skill source data, not a separate
Ansible role.

`roles/pi/files/package.json` is tracked by Renovate and protected by
`deps-guard`; it is not installed by this role. OMP plugin installation is
handled separately by the role's explicit plugin tasks.

## Kiro authentication

Plugin installation is unattended. OAuth is per user and must be completed on each computer:

```text
omp
/login kiro
```

Complete the browser sign-in. Then select `kiro/auto` with `/model kiro/auto`. The playbook does not set Kiro as the default model because the OAuth session is not present until a user signs in.

## Package source

The OMP and Bun Homebrew formulas are in `can1357/tap`; both are core packages for Homebrew-supported hosts. On musl, the official OMP binary installer verifies its SHA-256 and requires `libgcc` and `libstdc++`. Raw Termux receives neither OMP nor the obsolete Pi npm package.
