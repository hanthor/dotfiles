---
name: tunaos-contributor-fleet
description: Check on and unwedge the four local Hive contributor sessions (claude, codex, agy, pi) running as podman quadlets against both hive.tunaos.org and the Project Bluefin hive. Use when asked how the contributors/sessions are doing, when one looks idle or stuck, or when changing contributor config, backends, or hub subscriptions.
---

# tuna-os contributor fleet

Four contributor CLIs run as rootless podman quadlets, each subscribed to
**both** hubs (multi-hub relay patch, upstream PR kubestellar/hive#2846):

| service | backend | container |
|---|---|---|
| `pi.service` | pi (deepseek-v4-flash) | `pi` |
| `claude-contributor.service` | claude | `claude-contributor` |
| `codex-contributor.service` | codex | `codex-contributor` |
| `agy-contributor.service` | agy (Antigravity/Gemini) | `agy-contributor` |

Hub identities are **per-hub, not per-backend** — one contributor slot per
GitHub account per hive, so all four share `c-be093c7b6f07` (tunaos) and
`c-fda53676b337` (bluefin). Concurrency was raised on those profiles so they
don't block each other.

Config: `~/.config/hive-{claude,codex,agy}/contributor.env`, plus
`~/.config/containers/*.env`. Quadlets in `~/.config/containers/systemd/`.

## Check-in sweep

```bash
systemctl --user status pi claude-contributor codex-contributor agy-contributor \
  --no-pager | grep -E '●|Active:'

for c in pi claude-contributor codex-contributor agy-contributor; do
  echo "=== $c ==="
  podman logs --tail 8 $c 2>&1 | grep -vE '^\s*$'
done
```

Read the log lines, don't just check "Running":

- `Authenticated with <hub> as c-… (tier: …)` on **both** hubs → healthy.
- `No task assigned … reason: no_matching_work | hourly_limit` → **normal**.
  Idle because the queue has nothing admissible, not broken.
- `Task assigned: …` then `Task prompt sent to CLI` → working.
- `CLI not ready — queuing task prompt` → fine briefly, bad if it persists.
- `CLI did not become ready within timeout` → **wedged**, see below.

## When a backend is wedged

Always look at the actual pane before concluding anything:

```bash
podman exec <container> tmux capture-pane -pt contributor -S -25
```

Nearly always it's a **modal prompt** blocking startup. The CLI looks alive and
its banner is on screen, but it's sitting on a menu. Known ones:

- codex directory-trust: `Do you trust the contents of this directory?` → send `1`
- codex update nudge: `✨ Update available!` → send `3` (Skip until next
  version — **not** `1`, which runs `npm install -g` inside the container)

```bash
podman exec <container> tmux send-keys -t contributor "1" Enter
```

Both are auto-dismissed by the patched relay (PRs #2845 / #2849). If a *new*
prompt shape appears, add it to `blockingPromptKey()` rather than hand-nudging
forever — hand-nudging doesn't survive the next restart.

A wedged CLI used to black-hole its task: the relay logged the timeout and told
the hub nothing, so the slot stayed held. The patched relay hands the task back
(`task_failed`) and withholds `ready` until the CLI truly recovers.

## Relay: upstream now, not a local patch

**As of 2026-08-08 the local relay patch is gone for claude/codex/agy.**
Multi-hub (#2846, ported to v2 as #2861) and unresponsive-backend recovery
(#2849) were merged upstream, and `ghcr.io/kubestellar/hive-contributor:latest`
now ships them — the image is byte-identical to `origin/v4`'s
`bin/contributor-relay.sh`. Those three quadlets take the relay from the image.

**Do not re-add a bind-mount over `/usr/local/bin/contributor-relay.sh` there.**
Pinning a local copy silently reverts newer upstream work — when this was
checked, the image already had `classifyTmuxPane` / `paneLooksBlockedOnHuman`
(#2857, human-blocked pane detection) and `advanceActiveHub` (#2861) that the
local patch lacked.

`pi.container` is the exception: it runs a locally-built `pi-deepseek` image
(2026-08-03) whose bundled relay predates all of it, so it still mounts
`~/.local/share/hive-patches/contributor-relay.sh`. That file is a **verbatim
copy of upstream**, not a fork. Refresh it whenever v4 moves:

```bash
podman run --rm --entrypoint cat ghcr.io/kubestellar/hive-contributor:latest \
  /usr/local/bin/contributor-relay.sh > ~/.local/share/hive-patches/contributor-relay.sh
```

The real fix for pi is rebuilding `pi-deepseek` from current upstream, which
retires the mount entirely.

To check what any image actually carries:

```bash
podman run --rm --entrypoint grep <image> -c rawHubList /usr/local/bin/contributor-relay.sh
```

## Landmines

**`~/.config/hive/*.env` must be world-readable.** `pi.container` doesn't use
`UserNS=keep-id`, so rootless podman's remapped UID can't read `600` files and
the service crash-loops with `Permission denied`. Keep them `644`. This has
regressed more than once.

**Don't mount `~/.config/hive` into pi.** `contributor-agent.sh` sources
`contributor.env` *after* the quadlet's `Environment=` lines, so a stale
single-hub file there silently overrides multi-hub config even though
`podman inspect` shows the right value. pi gets everything from `pi.env`.

**CLI credential dirs are read-write on purpose.** `~/.claude`, `~/.codex`,
`~/.gemini` are mounted without `:ro` — the CLIs write session state at
runtime, not just credentials. `:ro` breaks Claude Code with `EROFS`. This also
means codex's trust answer persists in `~/.codex/config.toml`.

**TMPDIR redirect is required.** `/tmp` and `/var/tmp` are tiny (2G) tmpfs;
image pulls fill them. Quadlets set `Environment=TMPDIR=%h/.cache/podman-tmp`
and `containers.conf` sets `tmp_dir` to match.
