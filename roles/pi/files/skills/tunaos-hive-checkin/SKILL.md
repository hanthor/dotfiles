---
name: tunaos-hive-checkin
description: Check the health of the self-hosted tuna-os Hives (school at school.tunaos.org, reef at reef.tunaos.org, hub at hub.tunaos.org; Docker Compose on the Spindle VPS) — whether the governor and agents are actually producing PRs/issues, whether config changes really took effect, and where the known landmines are. Use when asked to "check on the hive", "is the hive working", "is it opening PRs", or when changing agent models/repos/config on school or reef.
---

# tuna-os Hive check-in

There are two self-hosted **spokes** and a **hub**, all Docker Compose services
under `/srv/hives` on the Spindle VPS (`ubuntu@100.113.75.88` over Tailscale):

| Service | Container | Public URL | GitHub App |
|---|---|---|---|
| school | `hives-school-1` | https://school.tunaos.org | `hanthor-hive-agent` |
| reef | `hives-reef-1` | https://reef.tunaos.org | `tuna-reef-hive` |
| hub | `hives-hub-1` (+ `hives-hub-front-1`) | https://hub.tunaos.org | — |

The old AWS Talos cluster (kubectl, `hive-operator`, CronJobs, the
`hive.reilly.asia` and `hive-hanthor` spokes) is gone; ignore any `kubectl`
instruction from older notes. Layout, roster, identity and the safe way to edit
config are in `docs/src/cluster/hive.md` (the mdBook page "Hive Agent Fleet",
section "Current deployment: Spindle VPS"). Read it before changing anything.

The spokes run their own agents; contributor CLIs are separate (see
`tunaos-contributor-fleet`). **Never print `dashboard.auth_token`, the GitHub App
key, `.env` or any `*_TOKEN`/`*_SECRET` env var.**

## Fast health sweep

```bash
ssh ubuntu@100.113.75.88 'docker ps --filter name=hives-'     # Up? uptime = recent restart?
for h in school reef; do
  curl -s -o /dev/null -w "$h %{http_code}\n" https://$h.tunaos.org/api/health   # 200
done
curl -s https://hub.tunaos.org/api/fleet-stats                  # hub has no /api/health (404)
```

Agent state needs the dashboard token. `dashboard.authorized_users` is set, so
the Bearer path is closed; use the server-to-server `X-Hive-Internal` header
from inside the container, expanding the token in the container's shell so it is
never echoed:

```bash
ssh ubuntu@100.113.75.88 'docker exec hives-school-1 sh -c \
  "curl -sS -H \"X-Hive-Internal: \$HIVE_DASHBOARD_TOKEN\" http://127.0.0.1:3002/api/status"' \
  | jq -r '.agents[] | [.name, .state, .paused] | @tsv'
```

Use `hives-reef-1` for reef. Agents showing `stopped` between governor kicks is
normal; a `paused` agent that nobody paused is not. Browser access is GitHub
sign-in for the allowlisted user (`hanthor:owner`).

## Health scale — check these in order

Each rung can be green while the one below it is broken.

1. **Container + API**: `docker ps` shows `Up` with a sensible uptime, and
   `/api/health` returns 200. A recent restart is expected after config edits or
   OOM kills (spokes are capped at 2560 MB; see the Hive page, "Known limits").
2. **No agent silently paused**: the `jq` filter above with `select(.paused)`
   should print nothing (`brainstorm` is on-demand). A paused agent costs
   governor cycles and its pause persists in `/data/hive-state.json` with no
   reason recorded.
3. **Logs**: `ssh ubuntu@100.113.75.88 'docker logs --since 30m hives-school-1 | tail -50'`
   for panics, OOM-kill restarts, or repeated errors. Do not paste output that
   may contain tokens.
4. **Is it producing?** (next section)

## The real question: is it *producing*?

"Container is Up" means nothing. Check authored work, per hive:

```bash
gh search prs --author "hanthor-hive-agent[bot]" --limit 20 \
  --json repository,number,title,createdAt,state      # school
gh search prs --author "tuna-reef-hive[bot]" --limit 20 \
  --json repository,number,title,createdAt,state      # reef
gh search issues --author "hanthor-hive-agent[bot]" --limit 20 \
  --json repository,number,title,createdAt
```

Filter by the **bot**, not by `hanthor` (the human account). Both hives set
`app_authored_prs: true` and `ai_author: ""`, so their work appears under the
App's `[bot]` login. If the newest item is days old while agents are up, the
hive is idle-but-alive: look at the governor and agent logs, and at whether the
shared agent pool is saturated (hub allows 2 concurrent sessions across both
spokes).

## Landmines

**Two sources of config; the runtime one wins.** `<spoke>/config/hive.yaml` is a
seed; the live file is `<spoke>/data/hive.yaml.runtime` and Hive may rewrite it
(reef's ACMM level differs between them). Edit both, with a backup into
`/srv/hives/backups/`, and verify the parsed result. Agent fields marked
`*_owner: operator` in the runtime file are kept across restarts; others can be
re-asserted by the ACMM policy pack (historical behaviour from v4–v6 on the old
cluster; unverified whether it still applies to every field).

**Never `docker compose up` a running spoke to apply config.** It triggered a
container-rename bug. Use `docker compose rm -f -s <spoke>`, edit, then
`docker compose up -d --no-deps <spoke>`. The exact procedure and a roster
helper are in the Hive page ("Safe edit procedure"). Other operators and agents
edit `/srv/hives` too: re-read files right before editing and never touch
someone else's in-flight edit.

**The running binary is not the image tag.** `compose.override.yaml` pins
`bin/hive-<sha>` and a matching dashboard HTML; its header comments are the
change log and rollback notes. Roll back one service at a time with `--no-deps`.

**Roster.** A repo belongs to exactly one hive (school or reef) unless it is
deliberately excluded; adding one needs only a roster edit in both files of the
target spoke (`project.repos` and `dashboard.matrix.repos`), since both Apps are
installed org-wide.

**Sentinel and Renovate.** Both hives set `sentinel.exempt_logins:
[renovate[bot]]` because Sentinel's `sensitive_path` rule flagged every
dependency bump. Do not "fix" that with `auto_merge.trusted_bot_authors`: it
would also let Hive auto-merge Renovate major bumps, which the org forbids.

**Hive's own CI is disabled** for `tuna-os/hive` ("Actions has been disabled";
support ticket pending), so fork builds are not CI-verified.

**Reply spam.** Hive can repeat its un-park replies on issues until upstream
hivecommons/hive#17512 (draft) lands.

## Operating from GitHub

On hive-managed issues and PRs: `/hive decision <instruction>`, `/hive approve`,
`/fixed`, and a GitHub review (approve or request changes) on PRs Hive did not
author. Hive removes the `blocked` label itself when it un-parks an issue.
Decision comments from the maintainer's agent start with
`Decision (for @hanthor):`.

## Pausing / resuming agents

Routes are `POST /api/pause/{agent}` and `POST /api/resume/{agent}` — not
`/api/agents/{agent}/resume`, which returns 405. On v6, `X-Hive-Internal` with
the dashboard token and **no** session cookie is owner-equivalent, so mutations
work headlessly (checked on the old cluster 2026-10-01; not re-run on Spindle).
Do not add a `hive_session` cookie alongside it — that scopes the request down
to that user's role.

```bash
ssh ubuntu@100.113.75.88 'docker exec hives-school-1 sh -c \
  "curl -sS -X POST -H \"X-Hive-Internal: \$HIVE_DASHBOARD_TOKEN\" http://127.0.0.1:3002/api/resume/<agent>"'
```

Confirm against `/api/status` rather than the response body.
