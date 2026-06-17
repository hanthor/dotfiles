# CONTEXT.md — dotfiles domain glossary

> Created 2026-06-14 during architecture review.
> Add terms as they are sharpened during grilling sessions or refactors.
> This is a glossary, not a spec. Implementation details live in `docs/roles.md`, `docs/cluster.md`, and ADRs.

## Fleet

- **Machine** — a physical host, VM, or VPS managed by this repo. Each has an entry in `inventory.yml` and `host_vars/<name>.yml`.
- **Fleet** — the set of all machines.
- **Group** — a logical subset of machines (`desktop`, `server`, `vps`, `llm`, `test_fleet`). Used by Ansible inventory groups and by `site.yml` `when:` conditionals.
- **Hostname** — the machine's short name (e.g. `karnataka`, `bihar`). Used as the inventory hostname, Tailscale hostname, and BW item key suffix.
- **Machine profile** — a proposed replacement for scattered `skip_*` flags. A single typed variable that declares a machine's role (e.g. `headless`, `desktop`, `vm-test`) and derives which components to install.

## Secrets

- **BW item** — a Bitwarden vault entry (login, secure note, SSH key) consumed by a role. Named items (e.g. `tailscale-apikey`, `atuin.sh`, `accounts.firefox.com`).
- **BW credential** — a single field extracted from a BW item (password, username, notes, TOTP, SSH key, custom field). The `bw_credential` Ansible module fetches these.
- **BW session** — the `BW_SESSION` environment variable that unlocks the vault for the current playbook run. Resolved from env → `/tmp/bw_session` cache → interactive unlock.

## Playbook

- **Role** — an Ansible role that configures one concern (e.g. `shell`, `tailscale`, `homepage`). The interface is `tasks/main.yml`; the implementation is templates, files, and handlers.
- **Phase** — a logical grouping of roles in `site.yml` (Phase 1: system + packages, Phase 2: secrets + auth, Phase 3: desktop, Phase 4: services). Phases are documented in comments, not enforced by the playbook.
- **Tag** — an Ansible tag applied to roles so `just apply-tags <tag>` can target a subset.

## Cluster

- **Node** — a Talos Linux machine in the K8s cluster (`bihar` = control plane, `karnataka` = worker).
- **Workload** — a Kubernetes deployment on the cluster (Lemonade, KubeVirt, Tailscale Operator).
- **Manifest** — a YAML file in `talos-k8s/` that defines a workload.

## Architecture (from improve-codebase-architecture)

- **Module** — anything with an interface and an implementation (a role, a script, a Just recipe, an Ansible module).
- **Interface** — everything a caller must know to use the module (task names, variables, tags, error modes, `when:` guards).
- **Depth** — leverage at the interface. A module is **deep** when a lot of behaviour sits behind a small interface.
- **Seam** — where an interface lives; a place behaviour can be altered without editing in place.
