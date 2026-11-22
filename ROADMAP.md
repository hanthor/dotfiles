# dotfiles — Roadmap

**Current Status**: Mature Ansible-managed infrastructure across 13 machines  
**Latest Release**: Continuous (auto-updates daily via systemd timer)  
**Last Updated**: 2026-11-20

---

## Overview

This roadmap reflects the strategic direction of the dotfiles infrastructure across personal machines, Kubernetes clusters (Talos, KubeVirt) and a Spindle VPS, and test fleets. The goal is **zero-touch operations**: machines bootstrap from bare metal to production-ready state with a single command, all secrets managed through Bitwarden, and all state synchronized automatically without a central server.

---

## Current Status

### Fully Operational

- **Shell environment**: fish + zsh + tmux with shared aliases across all machines
- **SSH key management**: Per-machine ed25519 keys synced via Bitwarden, automated cross-machine authorized_keys
- **Package management**: Homebrew (CLI tools) + Flatpak (desktop apps) with automated sync
- **Tailscale integration**: Auto-join mesh network with stored auth keys
- **Git configuration**: SSH signing, `gh` CLI auth, per-machine identities
- **Kubernetes clusters**: Talos (offline home cluster: bihar + karnataka), KubeVirt test fleet. The AWS Talos cluster was terminated on 2026-10-25; its retained S3 backups and punjab stay in place until #342 authorizes changes
- **Auto-updates**: Systemd timer pulls and applies changes daily to all machines
- **Bitwarden integration**: Secrets fetched at runtime, no git-stored credentials
- **GitHub Pages handbook**: Full documentation published at reilly.asia/infra/handbook

### Known Limitations

- **Offline cluster recovery**: Bihar + karnataka currently powered down (storage); startup playbook untested at scale
- **ARM device support**: Kerala (postmarketOS) requires manual `apk` tooling; needs dedicated role
- **CI/CD for roles**: No automated validation per role; handbook lists roles but no per-role testing
- **Secrets rotation**: Manual Bitwarden key rotation; no automated expiry or audit trail
- **Machine discovery**: Hardcoded in `inventory.yml`; no dynamic mesh discovery for new nodes

---

## Strategic Goals (Nov 2026)

Three goals now shape sequencing and take precedence over the older priorities below where they conflict. Each is a goal issue, not authorization for destructive changes.

### Goal A: Reduce ongoing AWS cost to $0 (#342)

- [ ] Inventory billing, resources and dependencies across regions
- [ ] Validate replacements (backup storage, restore procedure) before touching anything
- [ ] Apply only explicitly approved changes, then monitor billing until it reads $0

Guardrail: retained S3 backups and punjab are not deleted or stopped without an explicit per-change decision. This goal retires the Mid-Term "Multi-Region Failover" item.

### Goal B: Migrate fleet onboarding and configuration off Ansible (#343)

- [ ] Inventory roles, inventory/vars, secrets, scheduling and bootstrap paths; map each to a replacement
- [ ] Continue the staged mise/bash and chezmoi work (#331, #332, #334)
- [ ] Verify clean-laptop onboarding and existing-host upgrades end to end
- [ ] Remove Ansible entrypoints only after callers are migrated and verified

Until this completes, Ansible stays the supported path; Priority 2 (per-role CI) should favour checks that survive the migration.

### Goal C: Spindle VPS as the home for hosted services (#337, #338, #339, #340)

- [ ] Restore MatrixRTC calls (#338) and move off MAS (#339)
- [ ] Measure headroom, then decide whether the Hives move there (#340); the Always Free allowance may not fit both

### Supporting work

- Home server installer media built with Tacklebox (#318, #344, #351)
- Phone-QR secret onboarding (#49), which depends on the transport and bootstrap choices in Goal B
- Karnataka networking faults (#353, #354, #355), which gate the offline-cluster recovery below
- Delivery hygiene: restore the failing installer-acceptance check (#389), pin workflow actions by commit (#296), verify checksums of downloaded install scripts (#277) and centralise the Bitwarden fetcher (#279). These keep the Goal B migration verifiable
- Handbook accuracy: align architecture and service wiring (#291), the remote Bitwarden/SSH contract (#293), OMP/pi dependencies (#298) and GNOME skill links (#302), plus the provisioning and lifecycle write-up (#274, #275)

---

## Next 3 Months (Q4 2026)

### Priority 1: Offline Cluster Recovery

**Goal**: Enable reliable startup of bihar + karnataka from powered-down state

- [ ] Document power-up sequence (UPS, network, bootstrap order)
- [ ] Create `scripts/offline-cluster-bootstrap.sh` with idempotent startup validation
- [ ] Test full recovery from cold boot (KubeVirt, storage recovery)
- [ ] Publish recovery runbook in handbook (docs/src/servers/talos-k8s/recovery.md)

**Impact**: Reduces time-to-recovery from hours to minutes; enables disaster testing

### Priority 2: Multi-Platform CI Validation

**Goal**: Automatically test each role against target platforms

- [ ] Add GitHub Actions workflow: `test-roles.yml` (runs role subsets on VMs)
- [ ] Create test matrix: role × platform (Bluefin, postmarketOS, Ubuntu, Talos)
- [ ] Add `just test-role --role <name>` for local validation
- [ ] Publish role compatibility matrix in handbook

**Impact**: Catches breakage before applying to production machines; enables contributor confidence

### Priority 3: ARM Device Hardening

**Goal**: Make kerala (postmarketOS) first-class citizen, not exception

- [ ] Extract `postmarketos` role from desktop playbook (currently inline)
- [ ] Add apk-specific package management helpers
- [ ] Document ARM toolchain differences in handbook
- [ ] Test full bootstrap on actual device (not emulation)

**Impact**: Enables PostmarketOS deployment to other ARM devices; reduces maintenance friction

---

## Mid-Term (Q1-Q2 2027)

### Dynamic Machine Discovery

- Replace static `inventory.yml` with Tailscale-based discovery
- Machines auto-register when joining mesh
- Publish new onboarding flow (no git edits needed for new machines)

### Secrets Audit Trail

- Add Bitwarden API audit logging
- Track secret rotation, access, and changes
- Publish audit query templates in handbook

---

## Known Technical Debt

| Issue | Severity | Effort | Status |
|-------|----------|--------|--------|
| Offline cluster startup untested | High | 4-6h | Blocked on availability |
| ARM role extraction incomplete | Medium | 2-3h | Needs postmarketOS device access |
| CI validation missing per-role | Medium | 3-4h | Awaits GitHub Actions setup |
| Secrets rotation fully manual | Medium | 1-2d | Awaits Bitwarden API review |
| Machine discovery hardcoded | Low | 1-2d | Design phase; low urgency |

---

## Architecture Decision Points

1. **Cluster topology**: Talos for offline (air-gapped) vs. KubeVirt for development isolation — decision made; working as designed
2. **Secrets management**: Bitwarden single source of truth — decision made; working as designed
3. **Auto-updates**: Daily systemd timer pull + apply — working as designed; no changes planned
4. **Ansible idempotency**: All roles are fully idempotent — enforced; no exceptions

---

## Contribution Areas

### Low barrier to entry

- **Documentation**: Add runbooks for common operations (backups, restore, debugging)
- **Testing**: Write Bats tests for shell functions and scripts
- **Handbook**: Improve clarity of existing docs, add troubleshooting section

### Medium barrier

- **Role refactoring**: Extract cross-cutting concerns (logging, monitoring, notifications)
- **CI setup**: Add GitHub Actions workflows for role validation
- **Package management**: Add per-platform package pinning and update policies

### High barrier

- **ARM support**: Complete postmarketOS role extraction and testing
- **Dynamic discovery**: Implement Tailscale-based machine auto-registration

---

## Success Metrics

### Near-term (Q4 2026)

- **Zero manual bootstrap steps**: Full bootstrap from bare metal in one command
- **Role test coverage**: 80%+ of roles have automated CI validation
- **Offline cluster**: Bootstrap from cold shutdown succeeds 100% first-time

### Mid-term (Q1-Q2 2027)

- **AWS cost**: Ongoing AWS charges confirmed at $0 with restores verified
- **Ansible exit**: Clean-laptop onboarding and host upgrades verified without Ansible
- **Discovery**: New machines join inventory automatically without git edits
- **Audit trail**: All secret access logged and queryable

### Long-term (Year 2)

- **Contributor adoption**: 2+ external contributors maintaining roles
- **Deployment templates**: Reusable role bundles for common workloads (dev machine, server, Pi)
- **Community forks**: Evidence of successful forks/adaptations by others

---

## Out of Scope (Explicit Non-Goals)

- **Central management server**: This is single-user infrastructure; no multi-user auth model
- **Desktop GUI management**: Ansible CLI is the intended interface
- **Cloud provider abstraction**: No multi-cloud layer; hosted services target the Spindle VPS
- **Configuration templates for others**: Focus on personal machines first
- **Paid tooling**: Stick with open-source (Ansible, Bitwarden, Tailscale, GitHub)

---

## How to Contribute

1. **Report issues**: Open an issue describing what breaks or what's unclear
2. **Add tests**: Bats tests for scripts and role validation
3. **Improve docs**: Handbook PRs, runbooks, troubleshooting guides
4. **Add roles**: New roles must include role-specific README and idempotency tests

See [CONTRIBUTING.md](CONTRIBUTING.md) for how changes land and the local checks.

---

*Maintained by: strategist agent (hold-gated, human review required)*  
*Next review: 2027-01-15*
