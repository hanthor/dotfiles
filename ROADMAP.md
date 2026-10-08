# dotfiles — Roadmap

**Current Status**: Mature Ansible-managed infrastructure across 13 machines  
**Latest Release**: Continuous (auto-updates daily via systemd timer)  
**Last Updated**: 2026-10-08

---

## Overview

This roadmap reflects the strategic direction of the dotfiles infrastructure across personal machines, Kubernetes clusters (Talos, KubeVirt, AWS), and test fleets. The goal is **zero-touch operations**: machines bootstrap from bare metal to production-ready state with a single command, all secrets managed through Bitwarden, and all state synchronized automatically without a central server.

---

## Current Status

### Fully Operational

- **Shell environment**: fish + zsh + tmux with shared aliases across all machines
- **SSH key management**: Per-machine ed25519 keys synced via Bitwarden, automated cross-machine authorized_keys
- **Package management**: Homebrew (CLI tools) + Flatpak (desktop apps) with automated sync
- **Tailscale integration**: Auto-join mesh network with stored auth keys
- **Git configuration**: SSH signing, `gh` CLI auth, per-machine identities
- **Kubernetes clusters**: Talos (offline home cluster: bihar + karnataka), KubeVirt test fleet, AWS eu-north-1
- **Auto-updates**: Systemd timer pulls and applies changes daily to all machines
- **Bitwarden integration**: Secrets fetched at runtime, no git-stored credentials
- **GitHub Pages handbook**: Full documentation published at reilly.asia/infra/handbook

### Known Limitations

- **Offline cluster recovery**: Bihar + karnataka currently powered down (storage); startup playbook untested at scale
- **ARM device support**: Kerala (postmarketOS) requires manual `apk` tooling; needs dedicated role
- **CI/CD for roles**: No automated validation per role; handbook lists roles but no per-role testing
- **Multi-region failover**: AWS cluster isolated; no cross-region replication strategy documented
- **Secrets rotation**: Manual Bitwarden key rotation; no automated expiry or audit trail
- **Machine discovery**: Hardcoded in `inventory.yml`; no dynamic mesh discovery for new nodes

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

### Multi-Region Failover

- Replicate AWS cluster to second region (eu-west-1)
- Document failover procedures and RTO/RPO targets
- Publish multi-region runbook

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
| Multi-region documented but not tested | Low | 2-3d | Design phase |
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
- **Multi-region**: Design and test cross-region failover flows
- **Dynamic discovery**: Implement Tailscale-based machine auto-registration

---

## Success Metrics

### Near-term (Q4 2026)

- **Zero manual bootstrap steps**: Full bootstrap from bare metal in one command
- **Role test coverage**: 80%+ of roles have automated CI validation
- **Offline cluster**: Bootstrap from cold shutdown succeeds 100% first-time

### Mid-term (Q1-Q2 2027)

- **Multi-region**: Cross-region failover tested and documented
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
- **Cloud provider abstraction**: AWS-specific for now; multi-cloud later if demand appears
- **Configuration templates for others**: Focus on personal machines first
- **Paid tooling**: Stick with open-source (Ansible, Bitwarden, Tailscale, GitHub)

---

## How to Contribute

1. **Report issues**: Open an issue describing what breaks or what's unclear
2. **Add tests**: Bats tests for scripts and role validation
3. **Improve docs**: Handbook PRs, runbooks, troubleshooting guides
4. **Add roles**: New roles must include role-specific README and idempotency tests

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed instructions. All contributions must include DCO sign-off (`git commit -s`).

---

*Maintained by: strategist agent (hold-gated, human review required)*  
*Next review: 2026-12-15*
