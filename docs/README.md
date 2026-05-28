# Dotfiles & Infra Handbook

This book documents the personal fleet managed by this repo:

- **Workstations** — what each Ansible role does, how to onboard a new machine, where secrets live.
- **Infrastructure** — the Talos Kubernetes cluster running on `bihar` + `karnataka`, including the hardware, the AMD GPU integration, and how to bring it back from zero.

Build locally with `just docs` (serves on `http://localhost:3000`) or read individual files in [`docs/`](.) from the repo root.

The repo itself is at the root of this directory tree; see [`../README.md`](../README.md) for the high-level overview and the day-to-day `just` commands.
