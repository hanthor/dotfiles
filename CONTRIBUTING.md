# Contributing

This repo is applied, with sudo, by every fleet machine's daily timer from
`master`. That shapes everything below. Applies to humans, Renovate and Hive
agents alike.

## How changes land

`master` is protected: CI must pass and `.github/CODEOWNERS` requires code-owner
review. CODEOWNERS is deny-by-default; only paths that never run on the fleet
(docs, `*.md`, tests, `talos-k8s/`, pi skills, dependency manifests) are carved
out and can auto-merge once green. Hive PRs touching anything else are labelled
`needs-human`; Renovate's cluster bumps are labelled `deploy-needed` and are
never auto-merged. Details: [Bots, Agents & Guardrails](docs/src/automation.md).
Don't widen the carve-outs to anything the fleet timer executes.

## Local checks

```bash
yamllint -d "{extends: default, rules: {line-length: disable, document-start: disable, truthy: disable, comments-indentation: disable, comments: disable, braces: disable, indentation: disable, commas: disable, empty-lines: disable}}" .
# The commands below correspond to CI jobs; availability and results depend on your environment.
find . -name "*.sh" -not -path "./.git/*" -type f -print0 | xargs -0 shellcheck -x -S error
uvx --with pyyaml pytest -q tests
just --justfile Justfile --list
(cd aws && tofu fmt -check -recursive)
```

CI also checks JSON validity, compiles tracked Python, runs native osquery smoke jobs,
`tofu validate` + `aws/tests/run.sh`, and Go checks in `tools/secret-broker/`.
See `.github/workflows/ci.yml` for the current jobs. These instructions do not
assert that a particular checkout has passed them.

`just check` requests native unit inspection (`UNITS_CHECK=1`). Its coverage and
safety across platforms are subject to integration verification; do not assume
it is a complete dry-run guarantee. `just apply-tags <tags>` runs the selected
units and can change the host. Review [Architecture](docs/src/architecture.md)
and [Units](docs/src/units.md) before applying, especially for privileged work.

## Units and docs

- Add unit entrypoints and assets under `units/`, register them in `mise.toml`
  and `scripts/run-units.sh`, and implement platform, profile and privilege gates.
- Document behavior, limitations and secrets in the relevant handbook page.
  File-based shell, Git, Neovim and Atuin configuration comes from `home/` via chezmoi.

## Secrets

The repo is public. Secrets come from Bitwarden at runtime only — never
hardcode credentials, tokens or keys. Unit vault access uses a noninteractive
session and honors `UNITS_NO_SECRETS=1`; preserve existing secret data when unavailable.

## Don'ts

- Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, a kubeconfig,
  tofu state/plans, or `aws/terraform.tfvars`.
- Don't reintroduce NetBox; LAN inventory comes from `just inventory`.
- Don't add files to `karnataka/`; use `host_vars/karnataka.yml` or `talos-k8s/`.
- Don't rely on host sudo in automated/agent sessions.
- Don't restart anything on the retired `matrix`/`telengana` VPSes.
