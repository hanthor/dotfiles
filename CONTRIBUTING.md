# Contributing to dotfiles

Thanks for your interest in contributing to this Ansible-managed infrastructure. This guide covers the workflow, testing, and expectations for all contributions.

## Prerequisites

Before you start, ensure you have:

- **Ansible 2.15+** — Core orchestration runtime
- **just** — Command runner (replaces Make); install via Homebrew, apt, or from `just` GitHub releases
- **Git 2.34+** — For DCO sign-off (`git commit -s`)
- **Bitwarden CLI (bw)** — Optional, for local secret testing; not required for documentation or non-secret changes

### Local Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/hanthor/dotfiles.git
   cd dotfiles
   ```

2. Review available commands:
   ```bash
   just --list
   ```

3. For secret-dependent roles (Tailscale, SSH keys, GitHub auth):
   - Unlock your Bitwarden vault locally: `bw login` (if testing locally)
   - Or skip secret-dependent tasks for testing: `just apply-nosecrets`

## Making Changes

### Branch Naming

All branches follow conventional names:

- **Feature work**: `feat/<description>` — New roles, features, or capabilities
- **Architecture/refactoring**: `arch/<description>` — Tech debt, consolidation, decoupling
- **Fixes**: `fix/<description>` — Bug fixes, security patches, timeout additions
- **Documentation**: `docs/<description>` — README, handbook, runbook updates
- **Test coverage**: `test/<description>` — New tests or improved test infrastructure
- **Security**: `sec/<description>` — Security-related changes (not yet merged to main)
- **Dependency updates**: `deps/<description>` — Renovate-driven or manual dependency upgrades

Examples:
- `arch/extract-postmarketos-role` — Refactor ARM role
- `fix/offline-cluster-bootstrap` — Fix cold-start recovery
- `test/add-bats-tests-shell-functions` — Add shell function tests
- `docs/add-deployment-handbook` — New operational guide

### Commit Message Format

All commits must include DCO sign-off. Use conventional commit style:

```
[type]: [scope]: brief summary under 50 characters

Longer explanation here if needed. Wrap at 72 characters per line.

Closes #123  (if this commit resolves an issue)
or
Refs #456    (if this commit is part of a larger issue)

Signed-off-by: Your Name <your.email@example.com>
```

Examples:

```
fix: add timeout to tailscale install

Tailscale installation would hang indefinitely on network
timeouts. Add 30-second timeout to download and verify steps.

Closes #102

Signed-off-by: Jane Doe <jane@example.com>
```

```
arch: extract postmarketos role from desktop playbook

Move Android device configuration into a standalone role
for reuse across multiple PostmarketOS deployments.

Refs #150 (needs-human: device testing still needed)

Signed-off-by: Jane Doe <jane@example.com>
```

**Make commits with sign-off**:
```bash
git commit -s -m "type: scope: message"
```

## Testing Your Changes

### For Ansible Roles

1. **Dry run** — See what would change:
   ```bash
   just check
   ```

2. **Apply locally** (if you own the target system):
   ```bash
   just apply-nosecrets   # Fast; skips Bitwarden-dependent roles
   just apply             # Full apply with secrets (prompts for BW unlock)
   ```

3. **Role-specific tests** — If the role includes tests:
   ```bash
   cd roles/<role-name>
   # Check for role README and test instructions
   cat README.md
   ```

### For Scripts

Scripts in `scripts/` should have unit tests in `tests/`. Examples:

- `scripts/purge-machine.py` → `tests/test_purge_machine.py` (uses pytest)
- `scripts/bw-resolve.sh` → `tests/test_bw_scripts.py` (subprocess-based testing)
- Shell functions in configs → `tests/test_shell_functions.bats` (Bats)

**Run script tests**:
```bash
pytest tests/test_*.py -v          # Python tests
bats tests/*.bats                   # Bats shell tests
```

### For Documentation

- Test links: `just check-links` (if available)
- Build handbook locally: See `docs/README.md` if it exists
- Proofread for clarity and accuracy

## What Gets Reviewed

### Low barrier to entry (easier merges)

- ✅ Documentation improvements (README, handbook, runbook updates)
- ✅ Shell function tests (Bats tests for scripts in `scripts/`)
- ✅ Handbook troubleshooting sections
- ✅ Typo fixes and link corrections
- ✅ Comments and docstrings in roles/scripts

### Medium barrier (more scrutiny)

- ⚠️ New roles or major role refactoring (needs architecture review)
- ⚠️ CI changes (affects all machines; needs test coverage)
- ⚠️ Dependency updates (security implications; needs changelog review)
- ⚠️ Cross-role coordination changes (affects idempotency guarantees)

### High barrier (extensive review)

- 🔒 New support for ARM or other platforms (device testing required)
- 🔒 Multi-region or failover logic (operational testing required)
- 🔒 Secrets management changes (security audit required)
- 🔒 Offline cluster recovery procedures (disaster testing required)

## Pull Request Expectations

### PR Title

Use conventional commit format (matches your branch and commits):

```
type: scope: brief summary
```

Examples:
- `docs: add CONTRIBUTING.md with developer onboarding`
- `fix: add timeout to GitHub API profile import`
- `arch: extract shared error helpers from tts service`

### PR Description

Include:

1. **What changed** — Summary of the work
2. **Why** — Problem it solves or improvement it brings
3. **How tested** — What you ran locally
4. **Closes/Refs** — Issue reference (e.g., `Closes #123`)

Example:

```markdown
## Changes

Extracts `postmarketos` role from monolithic `desktop` playbook.

## Why

PostmarketOS devices (ARM) need different package managers (apk) and
boot procedures than desktop systems. Separating the role enables:
- Reuse for other ARM deployments
- Clearer testing matrix
- Easier onboarding of ARM-specific tooling

## Testing

- Tested on actual PostmarketOS device (nokia 5.1 Plus)
- Verified idempotency: `just apply` runs twice with no changes
- All apk packages install correctly; firmware tools available

Closes #150

---
*Filed by contributor. DCO sign-off required.*
```

### Before Opening the PR

1. **Rebase** on the latest `master`:
   ```bash
   git fetch origin master
   git rebase origin/master
   ```

2. **Push your branch**:
   ```bash
   git push -u origin strategy/contrib-guide
   ```

3. **Open the PR** via GitHub web UI or `gh pr create`:
   ```bash
   gh pr create --title "docs: add CONTRIBUTING.md" \
     --body "Adds developer onboarding guide..."
   ```

## Code Style & Conventions

### Ansible

- Use 2-space indentation in YAML
- All roles must be **fully idempotent** — running twice produces no changes
- Use role README.md to document role variables and dependencies
- Avoid global state; pass context via role variables

### Shell Scripts

- Use `set -euo pipefail` at the top of shell scripts
- Quote all variables: `"$var"` not `$var`
- Use `mktemp` for temporary files; clean up with `trap`
- Add timeouts to network calls: `curl --max-time 30`
- Document script purpose and usage in a header comment

### Python Scripts

- Follow PEP 8 style (use `black` or similar)
- Add type hints where possible
- Use `subprocess.run(..., timeout=30)` for external calls
- Log errors and exit with non-zero status on failure
- Add a module docstring describing purpose

### Tests

- Tests live in `tests/test_*.py` (pytest) or `tests/*.bats` (Bats)
- Mock external services (SSH, Bitwarden, GitHub)
- Test both happy path and error cases
- Aim for >80% coverage on scripts and roles

## Review Process

1. **You open the PR** — Automated checks run (DCO, linting, tests)
2. **Maintainer reviews** — Expects response within 48 hours for `roadmap` items, best effort otherwise
3. **Address feedback** — Push new commits to the same branch (no need to reopen)
4. **Auto-merge** — Once approved and checks pass, PR merges automatically
5. **Deployment** — Changes roll out to machines via daily `just apply` timer

## Common Questions

### Do I need to test this on an actual machine?

**For roles**: Ideally yes, at least once. If not possible, detailed manual testing instructions in the PR help reviewers validate.

**For scripts**: Unit tests are required. If it touches the file system, use temp fixtures.

**For docs**: Just review for clarity and broken links.

### What if my change breaks existing machines?

All roles are idempotent, so rolling out a fix is one `just apply` away. However:

- Test locally first with `just check` or `just apply-nosecrets`
- If you can't test locally, provide clear rollback instructions in the PR
- If it's a security fix, mark the PR with `security` label

### How long does review take?

- **Roadmap items**: 24–48 hours
- **Bug fixes**: 24–48 hours  
- **Documentation**: Best effort; usually within a week
- **External contributions**: Best effort; aim for within a week but may take longer

### What if I disagree with feedback?

Open a discussion in the PR comments. If you can't reach consensus, a maintainer will make the final call. This is a personal infrastructure project, so some preferences are intentional design decisions (e.g., "no central server," "Bitwarden single source of truth").

## Getting Help

- **Architecture questions**: Open an issue with `[design]` prefix
- **Testing help**: Ask in the PR; include error logs
- **Handbook or runbook questions**: Ask in the PR or check reilly.asia/infra/handbook
- **Role-specific questions**: Check the role README.md first

## Running Full CI Locally

To simulate the full CI pipeline before pushing:

```bash
# Linting and format checks
ansible-lint roles/*/

# Python tests
pytest tests/ -v

# Shell tests
bats tests/*.bats

# Idempotency check (if you can test on a target system)
just check
just apply-nosecrets

# Check docs links
# (Add a docs link checker if handbook is markdown-based)
```

## Roadmap & Strategy

This project maintains a 12-month roadmap in [ROADMAP.md](ROADMAP.md). Before starting major work, check:

1. Is this work already in the roadmap?
2. Is there an open issue for this area?
3. Does it align with the project's non-goals?

If you're unsure, open a discussion issue first. We're always happy to clarify strategic direction.

---

## Summary

- **DCO sign-off required** — `git commit -s`
- **Conventional commit messages** — `type: scope: message`
- **Test locally** — `just check` and `just apply-nosecrets`
- **Document and test scripts** — Python/Bats tests required
- **Roles must be idempotent** — Running twice = no changes
- **Link to issues** — `Closes #N` or `Refs #N (needs-human: reason)` in PR body
- **Review expects 24–48h** for roadmap items, best effort otherwise

Thank you for contributing to dotfiles! 🙏
