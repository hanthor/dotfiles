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

## Audio (from pipewire DSP grilling)

- **DSP chain** — a PipeWire filter-chain module that processes audio through a graph of plugins (biquads, LADSPA, or LV2). Each chain creates virtual sinks/sources that apps connect to.
- **Bootc-compatible DSP** — a DSP chain that uses only PipeWire built-in plugins (e.g. `bq_peaking`, `bq_highpass`) with zero external package dependencies. Deployable on immutable bootc systems without image rebuilds.
- **LV2 DSP** — a DSP chain that uses LV2 plugins (e.g. `lsp-plugins` for parametric EQ, compressor, limiter). Higher quality but requires `lsp-plugins-lv2` in the base image.
- **Mic-DSP link** — the systemd oneshot service that routes the hardware microphone into a filter-chain and sets the default source. Exists because WirePlumber 0.5 does not auto-route hardware sources into passive filter inputs.
- **Filter-chain config directory** — `~/.config/pipewire/pipewire.conf.d/`. Filter-chain module configs must live here to be auto-loaded by the system PipeWire daemon. The `filter-chain.conf.d/` directory is only scanned by a standalone filter-chain process (`pipewire -c filter-chain.conf`), not by the main daemon. The official `source-rnnoise.conf` comment is misleading on this point.
- **Mic hardware volume** — a host-specific percentage (default 100) limiting the ALSA capture gain to prevent peaking on machines with hot microphones. Set via `mic_hardware_volume_pct` in `host_vars/`.
- **Per-machine speaker tuning** (future) — the current 16-band biquad EQ curve is a one-size-fits-all preset migrated from Easy Effects. Per-machine tuning would require: (1) a measurement methodology using a reference microphone and pink noise, (2) a tool to generate EQ curves from measurements (e.g. REW, AutoEQ), (3) per-machine profiles in `host_vars/` driving a Jinja2-templated filter-chain config. Not built yet.
