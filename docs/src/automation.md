# Self-improving repo: bots, agents and guardrails

This repo is edited by bots, and every fleet machine pulls `master` daily and
applies it **with sudo**. A bad merge therefore reaches every machine within
24h. The automation below is set up so that routine improvements land without
you, and anything that executes on the fleet still waits for you.

## Who changes what

| Actor | What it does | Merges by itself? |
|---|---|---|
| **Renovate** | minor/patch/digest bumps (pi npm deps, Go, GitHub Actions, OpenTofu providers), weekly lockfile maintenance | yes, once CI is green |
| **Renovate** (cluster) | image/chart bumps in `talos-k8s/`, grouped weekly, label `deploy-needed` | **no** — manifests are applied by hand, so a merge would only make git lie about the cluster |
| **Hive** (school, reef and hanthor spokes on [bihar, with karnataka as standby](cluster/hive.md#current-deployment-bihar-karnataka-standby); Apps `hanthor-hive-agent` and `tuna-reef-hive`) | its agents open PRs labelled `hold`; the Hive itself only merges PRs labelled `lgtm` | only if the PR stays inside the carve-outs below. school and reef cover only `tuna-os/*`; the **hanthor** spoke (hive.reilly.asia, see below) lists this repo in its roster, so Hive PRs here come from it |
| **You** | direct pushes, `just onboard`, etc. | admin bypass — unaffected |

## The gate

Three pieces, and none of them trusts the PR itself:

1. **Branch protection on `master`**: required checks `lint`, `python`,
   `tests`, `justfile`, `broker`, `deps-guard`, `tofu`,
   `osquery-smoke (ubuntu-24.04)` and `osquery-smoke (ubuntu-24.04-arm)`, plus
   **code-owner review**. Admins can bypass, so your own pushes still work.
2. **[`.github/CODEOWNERS`](https://github.com/hanthor/dotfiles/blob/master/.github/CODEOWNERS)**
   is deny-by-default (`* @hanthor`). The paths carved out are the ones that
   never run on a fleet machine: `docs/`, `*.md`, `tests/`, `talos-k8s/`, pi
   skill text, and dependency manifests. `.github/` is always owned, so nobody
   can loosen the gate from inside a PR.
3. **[`agent-automerge.yml`](https://github.com/hanthor/dotfiles/blob/master/.github/workflows/agent-automerge.yml)**
   queues GitHub auto-merge on every Hive PR. It runs from `master`'s copy
   (`pull_request_target`), never checks out PR code, and labels PRs that touch
   owned paths `needs-human`, with a comment listing the paths.

`deps-guard` lets Renovate change **versions** in `roles/pi/files/package.json`
but fails if a PR adds or removes a dependency. The manifest is tracked by
repository automation; the `omp` role copies `roles/pi/files/skills/` and
installs OMP plugins separately. It does not run `npm install` from this
manifest on fleet machines.

Secret scanning and push protection are enabled on the repository, so GitHub
blocks pushes that contain a recognised credential.

## Day to day

- Nothing to do for docs, tests or dependency bumps. They merge once green.
- Review anything labelled `needs-human` (Hive) or `deploy-needed` (Renovate,
  cluster). Nothing sends a digest of them; check the labels on GitHub.
- To let the Hive merge more, carve the path out in CODEOWNERS (and mirror it
  in `agent-automerge.yml`'s comment logic). Only do that for paths that never
  execute on the fleet.

## Hive config lives on its volume

Each live spoke persists its configuration to `data/hive.yaml.runtime` next to
the seed `config/hive.yaml`, and the runtime file wins on restart, so roster or
level changes made in the dashboard stick. hive.reilly.asia is the `hanthor`
spoke on bihar (rebuilt 2026-11-19); its seed is
[`hives/hanthor/hive.yaml`](https://github.com/hanthor/dotfiles/blob/master/hives/hanthor/hive.yaml).
The AWS-era ConfigMap in `talos-k8s/hive/spokes/hanthor/manifest.yaml` is
history. For the live files, read-only inspection and the safe edit procedure,
see the
[Hive operations guide](cluster/hive.md#current-deployment-bihar-karnataka-standby):

```bash
ssh james@bihar 'sudo podman ps --filter name=hives-; sudo cat /var/srv/hives/hanthor/data/hive.yaml.runtime'
```
