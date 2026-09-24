# hive-upgrade: keep the Hives on upstream's latest release

A daily CronJob in the **AWS Talos cluster** (`export KUBECONFIG=~/.kube/config-aws-migration`) that moves our Hive deployments to upstream's newest v5 release. It goes one target at a time, soaks between targets, and rolls back and blocklists a release that fails.

| File | Deployed as |
|---|---|
| `hive-upgrade.sh` | ConfigMap `hive-upgrade-script` (key `hive-upgrade.sh`) in ns `hive` |
| `rbac.yaml` | ServiceAccount `hive-upgrade` (ns `hive`), Roles/RoleBindings in `hive-hanthor`, `hive-reef`, `hive`, `hive-hub`, read-only in `hive-contributors`, ClusterRole `hive-upgrade-nodes` |
| `cronjob.yaml` | CronJob `hive-upgrade` (ns `hive`), daily 04:30 America/New_York |
| state | ConfigMap `hive-upgrade-state` (ns `hive`), created on the first real run |

Tests: `uvx --with pyyaml pytest -q tests/test_hive_upgrade.py`

## What it manages

In this order. The first target is the canary.

| # | Target | Deployment / container | Check |
|---|---|---|---|
| 1 | `hive-hanthor` (canary: personal, unbranded) | `hive` / `hive` | Ready, no crashloop or restarts, `GET :3002/api/health` = 200, and the owner dashboard serves HTML |
| 2 | `hive-reef` (branded REEF) | `hive` / `hive` | the same, plus the **owner dashboard contains `product_name` and `mark`** from `/data/branding/branding.json` |
| 3 | `hive` (branded SCHOOL, school.tunaos.org; legacy alias hive.tunaos.org) | `hive` / `hive` | the same as reef |
| 4 | `hive-hub` (hub.tunaos.org) | `hive-hub` / `hub` | Ready, and `GET /` through the Service returns 200 with the hub page |

Spokes run `ghcr.io/hivecommons/hive:<tag>@<digest>` and the hub runs `ghcr.io/hivecommons/hive-hub:<tag>@<digest>`. The contributors in `hive-contributors` run `ghcr.io/kubestellar/hive-contributor:latest`. The script only reports on them and never changes them.

## Why it works this way

**Upgrade daily to the newest release, not on every release.** Upstream cuts several v5 releases an hour. Following each one would restart hive and hive-reef many times a day. Every restart triggers boot-time GitHub rescans, and both hives share one GitHub App installation (7150 req/h). Once a day at a quiet hour is enough to stay current. If a release is bad, upstream usually supersedes it within hours, and the blocklist skips it in the meantime.

Other ways we could have done it:
- **`TRACK=stable`**: upstream's soak-gated channel, about a day behind.
- **`TRACK=candidate`**: moves on every green v5 merge.

Both are supported. The script resolves the channel tag to a digest and records the version as `stable@<12 hex>`. The default stays on real release tags because they are human-readable, can be blocklisted, and can be compared as semver, which the downgrade guard relies on.

Upstream's Kubernetes guidance is a rolling `kubectl set image` to a digest, not their podman auto-update profile. That is what this does, with safety checks added around it.

**Canary → soak → next.** `hive-hanthor` is personal and unbranded, so it goes first. After each target passes verification, the script watches it for `SOAK_SECONDS` (default 600) before moving on:
- It re-checks every `SOAK_INTERVAL` (default 60s): pod not restarted and not crashlooping, health 200, and branding on branded hives.
- It fails on two consecutive measured failures.

The soak also keeps the hive and hive-reef restarts about 10 minutes apart, so their boot scans don't hit the shared rate limit together.

**Failure → rollback that target, blocklist, stop, alert.** The failing target is patched back to its recorded previous image and re-verified. The version is added to the blocklist, and the run stops, so later targets are never touched. Targets that already upgraded stay upgraded, because they passed their own checks. If one of them is left on the now-blocklisted version, the next run moves it to the next eligible release, even when that is technically a downgrade. A cooldown of `COOLDOWN_HOURS` (default 20) blocks a same-day re-run after a rollback.

### Rules carried over from `hive-fork-switch.sh` (each one was learned from an incident)

- **Digest, never a moving tag.** The image string is `repo:tag@sha256:…`. The digest is the sha256 of the exact index bytes GHCR served.
- **Architecture gate before any change.** Every node architecture (from `kubectl get nodes`) must be in both the spoke and hub image indexes, or the run aborts with no changes. `ghcr.io/kubestellar/hive:latest` was once arm64-only, and because the Deployments use `Recreate`, swapping to it took reef down.
- **"Could not measure" is never "unhealthy".** A kubectl, API or RBAC error, a missing owner session, or a `branding.json` with no marks is reported as UNKNOWN. After a change, a persistent UNKNOWN **aborts and alerts but does not roll back or blocklist**. The target stays on the new version, and its rollback target is in the annotation. Before a change, UNKNOWN or UNHEALTHY aborts with nothing changed.
- **Check content, not only status codes.** Branded hives are fetched *as an owner*, and the served page must contain their `product_name` and `mark`. Empty marks count as UNKNOWN, because `grep -F ""` matches every page. The predecessor ran `jq` inside the pod, but upstream v5 images don't ship it, so it compared against empty strings and every page passed.
- **Always a way back.** The same strategic-merge patch that changes the image also writes these annotations:
  - `hive.tunaos.org/previous-image`: the old `repo:tag@digest`. If the spec wasn't digest-pinned, the digest the pod actually runs is used instead. If neither can be found, the target is skipped.
  - `hive.tunaos.org/previous-version`
  - `hive.tunaos.org/version`
  - `hive.tunaos.org/upgraded-at`

  A rollback restores the old annotations and adds `hive.tunaos.org/rolled-back-from` and `hive.tunaos.org/rolled-back-at`.
- **Preflight.** Each target's *current* image must pass the same checks before it is changed. Otherwise a post-upgrade failure would prove nothing.

### Release selection (`TRACK=release`)

1. It reads `GET api.github.com/repos/hivecommons/hive/releases?per_page=50`, drops drafts and prereleases, and keeps tags matching `HIVE_UPGRADE_LINE` (default `^v5\.`). It then sorts them by semver, not by date or lexically, so `v5.35.10` ranks above `v5.35.9`.
2. **The cluster's shared egress IP usually has none of GitHub's 60 anonymous requests/hour left, because the hub spends them.** This was observed on 2026-09-24 as `remaining: 0` from both hub and hive pods. Without a `GITHUB_TOKEN`, the script falls back to the `github.com/hivecommons/hive/releases/latest` redirect. That is GitHub's own newest non-draft, non-prerelease release, and it isn't API-rate-limited. It gives only one candidate, though, so if that release is blocklisted the run holds. To get the full list in-cluster, create the optional secret: `kubectl -n hive create secret generic hive-upgrade-github --from-literal=token=<fine-grained PAT, public read>`.
3. It walks newest to oldest:
   - Blocklisted versions are skipped.
   - If a tag's image isn't published yet (404), it tries the next-older release, up to 5.
   - If a tag is published but lacks a node architecture, the run **aborts**.
4. A target already at the target digest is a no-op. A target on a *newer* non-blocklisted version is left alone (no downgrades) unless a pin is set.

## Running it

From a workstation, the script uses `~/.kube/config-aws-migration` unless `KUBECONFIG` is set. In the cluster, it uses the ServiceAccount.

```bash
cd talos-k8s/hive/upgrade

bash hive-upgrade.sh status                     # read-only: deployed vs target, blocklist, pin, last result
DRY_RUN=1 bash hive-upgrade.sh run              # full plan + read-only preflight checks; no patch, no state write, no Discord
DRY_RUN=1 HIVE_UPGRADE_PIN=v5.35.1 bash hive-upgrade.sh run   # exercise the whole path even when the fleet is current
bash hive-upgrade.sh run                        # real run from your machine (same as the CronJob)

# in-cluster, on demand:
kubectl -n hive create job hive-upgrade-manual --from=cronjob/hive-upgrade
kubectl -n hive logs -f job/hive-upgrade-manual
```

Knobs (env): `TRACK`, `HIVE_UPGRADE_LINE`, `HIVE_UPGRADE_PIN`, `DRY_RUN`, `FORCE` (ignores the cooldown and the run lock), `SOAK_SECONDS`, `SOAK_INTERVAL`, `VERIFY_ATTEMPTS`, `VERIFY_INTERVAL`, `ROLLOUT_TIMEOUT`, `COOLDOWN_HOURS`, `GITHUB_TOKEN`, `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` / `DISCORD_CONFIG`.

Exit codes:
- **0**: upgraded, nothing to do, or holding
- **1**: a target failed and was rolled back
- **2**: aborted (could not measure or resolve, architecture missing, or the rollback did not recover)

## Pin, block, unblock

These commands only edit `hive/hive-upgrade-state`:

```bash
bash hive-upgrade.sh block v5.36.0      # never deploy v5.36.0
bash hive-upgrade.sh unblock v5.36.0    # after upstream fixes it / it was a false alarm
bash hive-upgrade.sh pin v5.35.2        # always target exactly this (bypasses blocklist + no-downgrade guard)
bash hive-upgrade.sh unpin              # back to tracking TRACK
```

Pinning an older version is how you roll the whole fleet back deliberately. The next run takes it through the same canary, soak and verification path.

To roll back one target by hand, point it at its recorded rollback target:

```bash
ns=hive-reef
prev=$(kubectl -n $ns get deploy hive -o jsonpath='{.metadata.annotations.hive\.tunaos\.org/previous-image}')
kubectl -n $ns set image deploy/hive hive="$prev" && kubectl -n $ns rollout status deploy/hive
bash hive-upgrade.sh block <bad version>
```

## Discord

The script posts to #hive-ops (`hive_ops_channel_id` in ConfigMap `discord-report-config`) with the bot token from `discord-report-secrets`. It posts only:
- after a successful run that changed something: `Hive upgraded v5.35.2 → v5.36.0 (canary hive-hanthor ✓, reef ✓, hive ✓, hub ✓)`
- when a run fails, rolls back or aborts after changing something: one line starting with 🚨. Two 🚨s mean the rollback did not recover and someone needs to act.

No-ops, holds, and aborts before any change are not posted. They are in the job log and in `last_result` in the state ConfigMap. Payloads are built with `jq`, never with `printf` JSON, and have mentions disabled.

## Deploy

Review first. These commands change the live cluster.

```bash
export KUBECONFIG=~/.kube/config-aws-migration
cd talos-k8s/hive/upgrade

kubectl apply -f rbac.yaml
kubectl -n hive create configmap hive-upgrade-script --from-file=hive-upgrade.sh --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f cronjob.yaml

# sanity-check the SA's permissions (all "yes" except the last)
for ns in hive-hanthor hive-reef hive hive-hub; do
  d=hive; [ $ns = hive-hub ] && d=hive-hub
  kubectl auth can-i patch deploy/$d -n $ns --as=system:serviceaccount:hive:hive-upgrade
done
kubectl auth can-i create pods/exec -n hive-reef --as=system:serviceaccount:hive:hive-upgrade
kubectl auth can-i get services/hive-hub:3001 --subresource=proxy -n hive-hub --as=system:serviceaccount:hive:hive-upgrade
kubectl auth can-i list nodes --as=system:serviceaccount:hive:hive-upgrade
kubectl auth can-i get secrets -n hive --as=system:serviceaccount:hive:hive-upgrade    # expect: no

# first in-cluster run as a dry run (no changes, no Discord)
kubectl -n hive create job hive-upgrade-dry --from=cronjob/hive-upgrade --dry-run=client -o yaml \
  | yq '.spec.template.spec.containers[0].env += [{"name":"DRY_RUN","value":"1"}]' | kubectl apply -f -
kubectl -n hive logs -f job/hive-upgrade-dry && kubectl -n hive delete job hive-upgrade-dry
```

After editing `hive-upgrade.sh`, re-run the `create configmap … | kubectl apply` line. The next Job picks it up.

## Superseded: the hive-fork-* CronJobs

These CronJobs are replaced by this job:
- `hive-fork-switch` (Mon 06:50)
- `hive-fork-verify` (daily 07:10)
- `hive-fork-drift` (daily 04:41)
- `hive-fork-ai-check` (Mon 06:20)

All four run as SA `hive-ops` from ConfigMap `hive-ops-scripts`. They were built for the tuna-os fork → `kubestellar/hive` swap, which is finished, and are broken: no RBAC, wrong upstream, and one-shot. `hive-upgrade` does not reuse `hive-ops`, `hive-ops-scripts` or any of their state, and `rbac.yaml` grants them nothing.

**Recommendation: suspend them.** On 2026-09-24 all four already showed `suspend: true`. The commands are idempotent:

```bash
for cj in hive-fork-switch hive-fork-verify hive-fork-drift hive-fork-ai-check; do
  kubectl -n hive patch cronjob "$cj" -p '{"spec":{"suspend":true}}'
done
kubectl -n hive get cronjob -o custom-columns=NAME:.metadata.name,SUSPEND:.spec.suspend | grep fork
```

Once `hive-upgrade` has a few good runs, delete them, along with the `hive-fork-*.sh` keys in `hive-ops-scripts` and `~/.local/state/hive-rotate/fork-*` on the `hive-ops-state` PVC.
