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

## Local checks (mirror CI, `.github/workflows/ci.yml`)

```bash
yamllint -d "{extends: default, rules: {line-length: disable, document-start: disable, truthy: disable, comments-indentation: disable, comments: disable, braces: disable, indentation: disable, commas: disable, empty-lines: disable}}" .
ansible-lint site.yml
find . -name "*.sh" -not -path "./.git/*" -type f -print0 | xargs -0 shellcheck -x -S error
uvx --with pyyaml pytest -q tests
just --justfile Justfile --list
(cd aws && tofu fmt -check -recursive)
```

CI also checks JSON validity, `py_compile`s tracked Python, runs
`tofu validate` + `aws/tests/run.sh`, and gofmt/vet/tests `tools/secret-broker/`.

Before applying a playbook change, dry-run it on a machine you own:

```bash
just check               # ansible-playbook --check --diff
just apply-tags <tags>   # apply only the roles you touched
```

Tags and `skip_*` host_vars flags are listed in
[Architecture](docs/src/architecture.md#available-tags).

## Roles and docs

- New role: `roles/<name>/`, wired into the right phase of `site.yml` with
  tags and any `when:` gate.
- Document it in `docs/src/roles/<name>.md` and add it to
  `docs/src/SUMMARY.md`.

## Secrets

The repo is public. Secrets come from Bitwarden at runtime only — never
hardcode credentials, tokens or keys. BW-using tasks gate on
`secrets_available | default(false)`.

## Don'ts

- Don't commit `talosconfig`, `controlplane.yaml`, `worker.yaml`, a kubeconfig,
  tofu state/plans, or `aws/terraform.tfvars`.
- Don't reintroduce NetBox; LAN inventory comes from `just inventory`.
- Don't add files to `karnataka/`; use `host_vars/karnataka.yml` or `talos-k8s/`.
- Don't rely on host sudo in automated/agent sessions.
- Don't restart anything on the retired `matrix`/`telengana` VPSes.
