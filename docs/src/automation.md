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
| **Hive** ([hive.reilly.asia](https://hive.reilly.asia), `hanthor-hive-agent`, ACMM L5) | its agents open PRs labelled `hold`; the Hive itself only merges PRs labelled `lgtm` | only if the PR stays inside the carve-outs below |
| **You** | direct pushes, `just onboard`, etc. | admin bypass — unaffected |

## The gate

Three pieces, and none of them trusts the PR itself:

1. **Branch protection on `master`**: required checks `lint`, `python`,
   `tests`, `tofu`, `justfile`, `broker`, `deps-guard`, plus **code-owner
   review**. Admins can bypass, so your own pushes still work.
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
but fails if a PR adds or removes a dependency. The pi role `npm install`s
that file on every machine.

## Day to day

- Nothing to do for docs, tests or dependency bumps. They merge once green.
- Review anything labelled `needs-human` (Hive) or `deploy-needed` (Renovate,
  cluster). The Discord daily digest lists them under **Needs you**.
- To let the Hive merge more, carve the path out in CODEOWNERS (and mirror it
  in `agent-automerge.yml`'s comment logic). Only do that for paths that never
  execute on the fleet.

## Hive config lives on its volume

hive.reilly.asia persists its live config to `/data/hive.yaml.runtime` and
restores it over the ConfigMap seed on every restart. Roster or level changes
made in its dashboard win. [`talos-k8s/hive-hanthor/hive.yaml`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/hive-hanthor/hive.yaml)
is the seed, re-synced to the runtime state on 2026-09-24. Before trusting it,
check the runtime file:

```bash
kubectl -n hive-hanthor exec deploy/hive -- cat /data/hive.yaml.runtime
```
