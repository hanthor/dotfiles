# Upgrading the VPS Spindle from the hotfix image to main

Status: **done 2026-11-07.** Production runs `ghcr.io/tuna-os/spindle:v0.1.1` (main `1d8dfd99`,
arm64 release image). The rehearsal below was run first, against a copy of production; both
blockers it found were cleared before the upgrade (see [Blockers](#blockers)).

Before the upgrade production ran `ghcr.io/tuna-os/spindle:outbox-hotfix-arm64`, built from
branch `ops/outbox-hotfix`. That branch is the Oct 22 `main` (`79f00253`) plus #723, the
legacy-media patch and the concurrent outbox (#794).

## The production upgrade (2026-11-07)

The procedure under [Production procedure](#production-procedure-once-the-blockers-are-cleared)
was followed as written, with the release tag `v0.1.1`:

| Step | Result |
|---|---|
| `docker pull` | `v0.1.1`, `arm64 linux` |
| Stop (05:22:53 UTC) and `cp -a` of the store | `data/store.pre-v0.1.1`, 3.4 GB |
| `migrate --list` / `--dry-run` | store and binary at schema 1/1/3; `intern-state-keys` "not needed"; "already at this binary's schema" |
| Start | listening at 05:24:58 (outage about 2 minutes); room warm-up finished, 118 rooms in 21.2 s |
| `/_matrix/client/versions`, `.well-known/matrix/client`, MAS discovery, `call.reilly.asia/sfu/get` | 200, 200, 200, 405 |
| First 8 minutes | 324 inbound `/send` answered 200, 156 PDUs accepted, 0 ERROR log lines |

The compose file before the upgrade is `/srv/spindle/compose.yaml.bak-20261107T052253`.

## What the rehearsal showed

The rehearsal compared main `1e8f6973` with hotfix `fe76489a`. Both were x86_64 release builds,
run on punjab, pinned to two cores (`taskset -c 0,1`, `TOKIO_WORKER_THREADS=2` as in
`compose.yaml`). The config was production's `spindle.toml` with these changes: scratch store path,
localhost binds, federation and push disabled, and no `[auth.delegated]` block. A scratch password
replaced MAS login for one account, set on the copy only.

The store was the live production store (2.7 GB including 2,371 media blobs). It was copied
read-only over Tailscale: `sudo nice -n 19 ionice -c3` tar, then rsync, then a final rsync pass at
01:58 UTC. That final pass changed only the active journal (`89.jnl`). Nothing was written on the VPS.

| Check | Hotfix (baseline) | Main |
|---|---|---|
| Opens the copied store; `verify-media` | 2,371 blobs, all present (0.5 s) | 2,371 blobs, all present (0.4 s) |
| `migrate --list` / `--dry-run` | n/a | store at 1/1/3, only step `intern-state-keys` is "not needed"; dry-run and migrate: "already at this binary's schema" (0.5–0.6 s, writes nothing) |
| Rooms (admin API) | 118; 70,919 joined members; 105,020 state events | identical, same room-ID hash |
| State of the 15 largest rooms (up to 51,884 events) | event-ID hashes | identical hashes |
| Last 100 log entries of those rooms; `/messages` in 5 joined rooms | event-ID hashes | identical hashes |
| Accounts (admin API) | 1,360 | 1,360, same hash |
| Initial `/sync` for a local user (115 joined rooms, 2,103 timeline events) | 200 in 9.7–10.1 s | 200 in 9.1–11.0 s; same counts |
| Incremental `/sync` | 0.03 s | 0.03–0.06 s |
| Cold start (page cache dropped): listening / warm-up done (118 rooms) | 1.0 s / 14.2 s | 0.4 s / 12.0 s |
| Largest room cold load (≥1M bucket) | 1.04 s cold, 5.37 s on first run | 1.06 s cold, 1.70 s on first run |
| RSS after probe | 2.9 GiB | 2.8 GiB |
| WARN/ERROR log lines | 0 | 0 |
| Write path: send message, upload media, restart, read back | n/a | message found, media 200, `verify-media` 2,372/2,372 |
| **Rollback**: hotfix binary on the store after main ran and wrote | n/a | opens; same room/state/timeline/account hashes; 0 WARN/ERROR |
| Legacy `GET /_matrix/media/v3/download` and `/thumbnail` | **200** | **404** (see Blockers) |

Other measurements on the copy (main binary, offline):

- `spindle backup` took 15.7 s and wrote 16.7 M rows into a 4.0 GB file. The backup holds rows,
  not media.
- `spindle gc --dry-run` took 64.5 s and found 364,697 unreachable state nodes (290 MB) that
  could be swept.

Production warm-up is slower than on punjab. The 2026-11-06 restarts logged 19.2 s and 59.9 s for
the same 118 rooms on the hotfix image. Budget about a minute of degraded service after the
container starts.

No data migration runs. The store's schema (key 1, record 1, content digest 3, fjall 3) is the
same in both builds, so `migrate` is a no-op. The rollback is a plain image swap, and the rehearsal
exercised it.

Behaviour that changes with main and is not a data question:

- Per-user rate limits now default to Synapse's numbers: messages 0.2/s with burst 10, local
  joins 0.1/s with burst 10, room creation 0.016/s with burst 10, media uploads 10/s with burst 50.
  Production's config sets none of these. There are no appservices, so no bridge is affected.
- The MAS introspection verdict is cached for 120 s
  (`[auth.delegated] introspection_cache_ttl_secs`). A revoked MAS session can work for up to two
  minutes.
- Production's `spindle.toml` parses unchanged under main. The rehearsal checked this by starting
  main with that file, delegated block included.

## Blockers

Both were cleared before the upgrade:

1. **Legacy media.** Production depends on the frozen unauthenticated media endpoints
   (`/_matrix/media/v3/download|thumbnail`), which pre-MSC3916 clients use for avatars and
   thumbnails. The rehearsal found `main` returned 404 there. `tuna-os/spindle#736` merged before
   `v0.1.1`; it serves local media and remote media already cached, and never fetches uncached
   remote media without a token.
2. **No arm64 image of main.** `release.yml` builds amd64 and arm64 images for every `v*` tag;
   `v0.1.1` was cut from `main` `1d8dfd99` after #736, #800, #804 and #805 merged.

## Re-running the rehearsal (punjab)

The rehearsal needs about 3 GB for the copy, 3 GB for a working copy and 8 GB more if a backup
is taken. Everything stays in one mode-700 directory, which is deleted at the end because it
holds user data.

```bash
S=~/rehearsal-scratch; mkdir -p "$S/prod-copy/store" && chmod 700 "$S"
# Read-only copy of the live store. Run it twice; the second pass should only touch the journal.
rsync -a --delete --partial -z --rsync-path='sudo -n nice -n 19 ionice -c3 rsync' \
  ubuntu@100.113.75.88:/srv/spindle/data/store/ "$S/prod-copy/store/"
cp -a "$S/prod-copy/store" "$S/store"
# Binaries: cargo build --release -p spindle-server --bin spindle --locked at each commit.
OLD=spindle-hotfix; NEW=spindle-<tag>
CFG=$S/cfg/prodlike.toml   # production spindle.toml: storage path -> $S/store, binds on
                           # 127.0.0.1, federation/push disabled, [auth.delegated] removed
$OLD verify-media "$CFG"
$NEW promote-admin "$CFG" james
$NEW set-password-hash "$CFG" james < pw.hash   # argon2id of a throwaway password
$NEW migrate --list "$CFG"; $NEW migrate "$CFG" --dry-run
$NEW migrate "$CFG"; $NEW verify-media "$CFG"
TOKIO_WORKER_THREADS=2 taskset -c 0,1 $NEW "$CFG"
# Probe the server: admin API /_spindle/admin/v1/rooms, rooms/{id}/state and
# rooms/{id}/timeline, users; client /joined_rooms, /messages and /sync;
# metrics spindle_room_cold_* and spindle_room_warmup_*. Compare the results
# with a run of $OLD on a fresh copy.
rm -rf "$S"
```

The rehearsal compared runs by hashing event and room IDs, so the comparison files never held
message content. An incoming message on production during the copy window would show up as a
difference between the copy and production. It would not show up as a difference between the
two binaries.

The run on 2026-11-07 took about 40 minutes. Most of that was the copy: 2.7 GB over a DERP-relayed
Tailscale path at about 0.7 MB/s. All the checks together took under 5 minutes.

## Production procedure (once the blockers are cleared)

Run on the VPS in `/srv/spindle`. `<tag>` is the release tag, for example `v0.1.1`. Expected
outage: the time to stop and copy the store (seconds; 2.7 GB on local disk), plus about a minute
of warm-up.

```bash
cd /srv/spindle
# 1. Pull ahead of time; no outage.
docker pull ghcr.io/tuna-os/spindle:<tag>
cp compose.yaml compose.yaml.bak-$(date -u +%Y%m%dT%H%M%S)
sed -i 's#ghcr.io/tuna-os/spindle:outbox-hotfix-arm64#ghcr.io/tuna-os/spindle:<tag>#' compose.yaml

# 2. Stop Spindle and keep a byte-for-byte copy of the stopped store (includes media).
docker compose stop spindle
sudo cp -a data/store data/store.pre-<tag>

# 3. Migration plan; must say "already at this binary's schema" (rehearsed: no steps).
docker compose run --rm --no-deps spindle migrate --list /etc/spindle/spindle.toml
docker compose run --rm --no-deps spindle migrate /etc/spindle/spindle.toml --dry-run
docker compose run --rm --no-deps spindle verify-media /etc/spindle/spindle.toml

# 4. Start and watch warm-up.
docker compose up -d spindle
docker compose logs -f spindle | grep -m1 'room warm-up finished'
```

If the dry run lists any step other than "not needed", stop. Swap the image back and investigate:
the rehearsal did not cover that step.

Checks after the start:

```bash
curl -s https://matrix.reilly.asia/_matrix/client/versions | jq '.versions[-1]'
curl -s -o /dev/null -w '%{http_code}\n' \
  https://matrix.reilly.asia/_matrix/media/v3/download/reilly.asia/<known-media-id>   # 200 (#736)
curl -i https://call.reilly.asia/sfu/get   # 405
```

Then:

- Log in through MAS in Element and confirm that sync completes.
- Send a message in a federated room and confirm a remote server receives it.
- Start a call.

### Rollback

The schema did not change, so rolling back is an image swap:

```bash
docker compose stop spindle
cp compose.yaml.bak-<stamp> compose.yaml
docker compose up -d spindle
```

The rehearsal opened a store that main had already written with the hotfix binary: same rooms,
state and timelines, no errors. Data written by features only main has (new keyspaces) is ignored
by the old binary.

Restore `data/store.pre-<tag>` only if the store itself is damaged:

```bash
sudo mv data/store data/store.bad && sudo mv data/store.pre-<tag> data/store
```

That restore loses everything written since the stop.

### Afterwards

- Delete `data/store.pre-<tag>` after a week without problems, and remove the old images
  (`outbox-hotfix-arm64`, `legacy-media-compat-arm64`, `perf-723-de17805-arm64`).
- Optional, offline, with a fresh copy taken first: `spindle gc` reclaims about 290 MB of
  unreachable state nodes. It took 64 s on the copy.
- Update the image row in [README.md](README.md) and delete the `ops/outbox-hotfix` branch.
