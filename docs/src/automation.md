# Self-improving repo: bots, agents and guardrails

This repo is edited by bots. Machines with the fleet update timer enabled pull
`master` and apply configuration with sudo. A bad merge can therefore reach
those machines unattended. Executable fleet changes require owner review.

## Who changes what

| Actor | What it does | Merges by itself? |
|---|---|---|
| **Renovate** | minor/patch/digest bumps (pi npm deps, Go, GitHub Actions), weekly lockfile maintenance | yes, once CI is green |
| **Renovate** (cluster) | image/chart bumps in `talos-k8s/`, grouped weekly, label `deploy-needed` | **no** — manifests are applied by hand, so a merge would only make git lie about the cluster |
| **Hive** ([hive.reilly.asia](https://hive.reilly.asia), `hanthor-hive-agent`, ACMM L5) | its agents open PRs labelled `hold`; the Hive itself only merges PRs labelled `lgtm` | only if the PR stays inside the carve-outs below |
| **You** | review onboarding and other owned changes | admin bypass is available, but onboarding uses a PR |

## The gate

Three pieces, and none of them trusts the PR itself:

1. **Branch protection on `master`**: verified required checks are `lint`,
   `python`, `tests`, `justfile` and `broker`, plus **code-owner review**.
   Admins can bypass, so your own pushes still work. On 2026-10-29, only the
   obsolete AWS `tofu` requirement was removed; the other check/application
   bindings were preserved. Its configuration is archived at
   [`dcbbfbc`](https://github.com/hanthor/dotfiles/tree/dcbbfbc/aws).
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
repository automation; the `omp` unit copies `roles/pi/files/skills/` and
installs OMP plugins separately. It does not run `npm install` from this
manifest on fleet machines.

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
made in its dashboard win. The `hive-config` ConfigMap in
[`talos-k8s/hive/spokes/hanthor/manifest.yaml`](https://github.com/hanthor/dotfiles/blob/master/talos-k8s/hive/spokes/hanthor/manifest.yaml)
is the seed, exported from the cluster on 2026-10-01. Before trusting it,
check the runtime file:

```bash
kubectl -n hive-hanthor exec deploy/hive -- cat /data/hive.yaml.runtime
```
