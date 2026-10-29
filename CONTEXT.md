# CONTEXT.md — dotfiles domain glossary

> Created 2026-06-14 during architecture review.
> Add terms as they are sharpened during grilling sessions or refactors.
> This is a glossary, not a spec. Implementation details live in `docs/src/roles/` and the cluster handbooks (`docs/src/servers/talos-k8s/cluster.md`, `docs/src/servers/aws-k8s/cluster.md`).

## Fleet

- **Machine** — a physical host, VM, or VPS managed by this repo. Each has an entry in `inventory.yml` and `host_vars/<name>.yml`.
- **Fleet** — the set of all machines.
- **Group** — a logical subset of machines (`desktop`, `server`, `vps`, `test_fleet`, `termux_hosts`; `llm` is dormant). Native units and scripts read inventory membership for their gates.
- **Hostname** — the machine's short name (e.g. `kanpur`, `punjab`). Machine selection uses `DOTFILES_MACHINE`, `/etc/dotfiles-machine`, then hostname; it keys host settings and BW item suffixes.
- **Machine profile** — a host variable used alongside `skip_*` flags; individual units decide how to interpret it, including `vm-test` exclusions.

## Secrets

- **BW item** — a Bitwarden vault entry (login, secure note, SSH key) consumed by a unit. Named items include `tailscale-apikey`, `atuin.sh`, and `accounts.firefox.com`.
- **BW credential** — a field extracted from a BW item (password, username, notes, TOTP, SSH key, custom field). Units perform their own lookups and handle unavailable items.
- **BW session** — `BW_SESSION` or a cached `/tmp/bw_session` value used by noninteractive unit helpers. Apply recipes may resolve an interactive session; `--no-secrets` suppresses unit vault access.

## Native configuration

- **Unit** — a Bash entrypoint in `units/` configuring one concern. `scripts/run-units.sh` orders prerequisite stages and runs independent selections via mise or a sequential fallback. A unit can report multiple step failures independently. See `docs/src/units.md`.
- **Tag** — a selection key mapped to units by `tasks_for_tag` in `scripts/run-units.sh`; unit-specific platform and profile gates still apply.
- **chezmoi source** — `home/`, containing managed shell, Git, Neovim and Atuin files. Secret files and procedural operations remain in units.

## Cluster

- **Node** — a Talos Linux machine in a K8s cluster. Home: `bihar` = control plane, `karnataka` = worker (powered down, expected back). AWS (`eu-north-1`): one control-plane + one worker. Neither is in `inventory.yml`.
- **Workload** — a Kubernetes deployment on a cluster (home: Lemonade, KubeVirt, Tailscale Operator; AWS: Matrix/ESS, the Hive, CFP dashboard).
- **Manifest** — a YAML file in `talos-k8s/` that defines a workload.

## Architecture (from improve-codebase-architecture)

- **Module** — anything with an interface and an implementation (a unit, a script, a Just recipe).
- **Interface** — everything a caller must know to use the module (commands, variables, tags, error modes and guards).
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
