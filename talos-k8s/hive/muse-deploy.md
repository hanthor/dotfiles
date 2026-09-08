# Deploying the `muse` (Muse Code) backend to the fleet

Status as of 2026-09-08: **DEPLOYED to the `hive` spoke.** Image, credential,
and rotation gate are all live. `hive-reef` and `hive-hanthor` are still on the
old image by choice — leave them there until muse has run a while.

## PRs

| Repo | PR | What |
|---|---|---|
| hivecommons/hive (was kubestellar/hive — the old name redirects) | [#6222](https://github.com/hivecommons/hive/pull/6222) | upstream backend support |
| tuna-os/hive | [#48](https://github.com/tuna-os/hive/pull/48) | same commit, fork build for the fleet |
| tuna-os/hive-operator | [#2](https://github.com/tuna-os/hive-operator/pull/2) | `.config/muse` in SharedAuth dirs |

## Why an image rebuild is unavoidable

The deployed `ghcr.io/tuna-os/hive:bc7cb9e` binary rejects the backend outright:

```
{"error":"unsupported backend \"muse\" (supported: claude, copilot, goose, codex,
 pi, bob, aider, gemini, agy, opencode, kilo, vllm, llm-d, litellm, watsonx; ...)"}
```

No rotation config places muse until a new image carries the `config.CLIBackends`
entry. Everything else below is downstream of that.

## Steps

**1. Build and push the image** (human — this session had no ghcr.io login)

```bash
git clone -b muse-backend https://github.com/tuna-os/hive.git && cd hive
podman login ghcr.io
SHA=$(git rev-parse --short HEAD)
podman build -f src/Dockerfile -t ghcr.io/tuna-os/hive:$SHA src/
podman push ghcr.io/tuna-os/hive:$SHA
```

The muse layer adds **~250–265 MB per arch** — the largest CLI in the image.
Expect a slower build and pull than usual.

**2. Roll the deployment**

```bash
export KUBECONFIG=~/.kube/config-aws-migration
kubectl -n hive set image deploy/hive hive=ghcr.io/tuna-os/hive:$SHA
kubectl -n hive rollout status deploy/hive
# confirm the backend is now accepted:
kubectl -n hive exec $POD -- curl -sS -X PUT -H "Cookie: hive_session=$SID" \
  -H 'Content-Type: application/json' -d '{"backend":"muse","model":"muse-spark-1.3-contributor"}' \
  http://127.0.0.1:3002/api/config/agent/<agent>/models
```

Do `hive` first and leave `hive-reef` / `hive-hanthor` on the old image until it
has run a while — that is the whole point of having three spokes.

**3. Add `META_API_KEY` to the spoke Secret** (human — pending key rotation)

The key used for verification was pasted into a chat transcript and is being
replaced. Use the **new** key.

```bash
kubectl -n hive patch secret hive-secrets --type merge \
  -p "{\"stringData\":{\"META_API_KEY\":\"$NEW_KEY\"}}"
# then add a matching env entry to the Deployment (envFrom secretRef, or an
# explicit env with secretKeyRef) — the container needs it in its environment,
# not just in the Secret.
```

Note this key becomes readable by every agent in the namespace.

**4. Apply the rotation patch**

`muse-rotation.patch` in this directory. Verified to apply cleanly:

```bash
cd ~/.local/share/dotfiles
git apply -p1 talos-k8s/hive/muse-rotation.patch
# then re-deploy the ops-scripts ConfigMap however the hive_ops role does it
```

It adds two things:

- a `T3|meta|muse|muse-spark-1.3-contributor` rung
- a `muse) echo meta` arm in `provider_of()`

The second is not optional. Without it `provider_of` returns `unknown` for muse
(its `muse-spark-*` ids match none of the model sniff patterns), and muse can
never be selected as a rung or accounted for in headroom / `LOGIN_BLOCKED`.
`meta` is deliberately its own provider pool, so an exhausted Meta account can
never wedge rotation off anthropic/openai/google.

**T2 and T3, and that is measured.** Artificial Analysis scores
"Muse Spark 1.2 (xhigh)" (slug `muse-spark-1-2`) at agentic index **44.2** —
on the same scale the live tier cache uses, that sits between
`claude-sonnet-5` (44.5) and `gpt-5-6-luna` (42.9), i.e. the second-strongest
T2 rung. Two caveats recorded in the script itself: the 44.2 is for the
**xhigh** effort variant while muse defaults to `high`, and AA scored the bare
`muse-spark-1.2` while hive runs `muse-spark-1.2-contributor`. muse is placed
**last within T2**, so every measured incumbent still wins whenever it has
headroom.

**THE MODEL ID IS 1.2, NOT 1.3.** muse's catalog is caller-dependent: the same
key returned seven ids from a workstation and only four from inside the pod.
`muse-spark-1.3-contributor` does not exist in-cluster and fails at task time.
Always resolve the id from the pod, not a laptop.

## What was already verified

- `muse exec` argv, exit codes (0/1/2), and sandbox posture — see PR #6222.
- The pinned image fetch: checksum OK, binary runs.
- muse 1.0.3 installed on the `hive` PVC (`/data/home/.local/bin`) and runs in
  the live pod. That was **pre-flight only** — once the image ships,
  `/usr/local/bin/muse` comes from the layer and the PVC copy can be deleted.

## The bug promoting muse exposed (fixed in muse-rotation.patch)

Putting muse at T2 alone did **nothing** — the plan still stranded every agent.
`provider_ok()` admits an unmeasured provider only when its note matches
`no-agent` or `no-usage-api`:

```bash
if [ "$pct" = "-1" ]; then
  case "$note" in
    *no-agent*|*no-usage-api*) : ;;
    *) return 1 ;;      # <- meta had NO note, so every muse rung was rejected
  esac
fi
```

`gather()` only probed `deepseek anthropic openai google`, so `meta` was never
measured, had no note, and hit the catch-all. **muse's rungs were unselectable
at any tier** — the T2 promotion would have looked applied and silently done
nothing.

Two fixes:

1. **`probe_meta`.** muse has no usage/quota endpoint at all (no `usage`
   subcommand; `/v1/models` carries no quota fields), so it honestly reports
   `no-usage-api` — the fallback `provider_ok` documents but nothing had ever
   exercised. What it *can* verify is that the credential works **and that the
   exact model rotation places is in this pod's catalog**, which matters
   because that catalog is caller-dependent. Reports `100` (stay off) for a
   dead credential or a missing model.
2. **`PROVIDERS` defined once.** The provider list was hand-copied into four
   loops (`gather`, the stale-reset sweep, `publish_usage`, the probe display).
   Adding a provider to only some of them is a silent failure of exactly the
   kind above, so all four now derive from one variable.

Confirmed working:

```
PROVIDER    USED      NOTE
deepseek    100%      balance=-1.23
anthropic   unknown   unparsed
openai      100%      codex-5h=100% weekly=79%
google      100%      resets=2026-09-10T18:23:19Z
meta        unknown   no-usage-api      <- credential valid, model entitled
```

## Fleet provider state at deploy time (2026-09-08 02:0x UTC)

```
PROVIDER    USED      NOTE
deepseek    100%      balance=-1.23      <- NEGATIVE, needs a top-up
anthropic   unknown   unparsed
openai      100%      codex-5h=100% weekly=79%
google      100%      resets=2026-09-10T18:23:19Z
```

Every provider was exhausted simultaneously, which is why 11 of 12 agents were
paused ("STRANDED (no rung at T1/T2) -> pausing"). This pre-dates the muse work
— the 01:40 run showed it before any change here. Promoting muse to T2 gives
the fleet a rung with actual headroom; it does not fix the underlying problem.
**deepseek's negative balance is the one to act on** — it is the designated
no-cap availability net.

## Unrelated things found while surveying the fleet

- **11 of 12 agents in `hive` are paused**; only `supervisor` is active.
- `hive-cli-update` failed for `hive` with **exit 137**; reef and hanthor
  updated pi 0.84.1 → 0.85.1 fine.
- `pi-codex-contributor` in `hive-contributors` **Evicted ~38h**, node low on
  ephemeral-storage.
- `hive-operator`'s `sharedauth` controller errors steadily (`primary not
  writable`); no `ModelLadder` resource exists at all.
