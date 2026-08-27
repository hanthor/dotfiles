---
name: bst-desktop-repos
description: Operating the TunaOS BuildStream desktop-image repos (tromso/KDE, xfce-linux/XFCE, razorfin/COSMIC, zirconium-hawaii/Niri) — multi-runner CI, live-ISO pipeline, LUKS e2e, source tracking. Use when building/debugging these repos or porting the stack to a new desktop repo.
---

# TunaOS BuildStream desktop repos

Four sister repos build vanilla-from-source desktop bootc images, modeled on
projectbluefin/dakota (+ dakota-iso for the ISO/e2e side):

| Repo | Desktop | Junction | Installer flatpak |
|---|---|---|---|
| tuna-os/tromso | KDE Plasma (+ Aurora layer) | hanthor/kde-build-meta | org.tunaos.InstallerKde |
| tuna-os/xfce-linux | XFCE Wayland (xfwl4) | gnome-build-meta (gnome-50) + freedesktop-sdk | org.tunaos.InstallerXfce |
| RazorfinOS-org/cosmic-build-meta | COSMIC (complete bst OS repo: signed ISOs, own cosmonaut-installer, track-sources; lacks multirunner + e2e) | freedesktop-sdk | cosmonaut-installer (native) |
| zirconium-dev/zirconium-hawaii | Niri (CASD remote cache; **no AI-generated issues/PRs — maintainer preference**) | freedesktop-sdk | org.tunaos.InstallerNiri |

Canonical, fully-wired references: **tromso** and **xfce-linux** (as of
2026-07-19; see each repo's `docs/ci-and-iso-pipeline.md`).

## The stack every repo should have

1. **Multi-runner build workflow** — plan (`scripts/ci-build-matrix.py`) →
   core → N dep chunks (matrix) → final assembly; CAS shared as zstd
   tarballs on GHCR (`cache-<image>-{core,chunkN}` oras artifacts). BST
   settings in checked-in `buildstream-ci.conf`. Port from either reference
   repo — it's parameterized by `IMAGE_NAME`/`BST_TARGET` env at the top.
2. **ISO pipeline** — dakota-iso `iso.justfile` recipes (`container`,
   `iso-sd-boot`, `boot-iso-*`), 3-stage `<target>/Containerfile`
   (payload → Debian dracut dmsquash-live initramfs → live config), a
   `95<target>-isofile` Ventoy dracut module, chained to the build via
   `workflow_run`, with a hard `<TARGET>_LIVE_READY` serial boot gate +
   QEMU screenshot artifact.
3. **LUKS e2e** — `test-luks-install.yml` + `luks-*-qemu` recipes +
   `src/luks-unlock.py`; screenshots published to a `ci-screenshots` branch
   and PR comments.
4. **Installer baking** — desktop-matching `org.tunaos.Installer*` from the
   tuna-os OCI remote (`https://tunaos.org/flatpak/tuna-os.flatpakrepo`),
   ISO-only (never OS images), fisherman symlinked to
   `/usr/local/bin/fisherman`, shared `org.tunaos.Installer.install` polkit
   action + liveuser rule. Contract: `INSTALLER-FRONTENDS.md` in the
   tuna-os workspace.
5. **Updates** — renovate.json (Actions/containers, automerge incl. major)
   + `track-bst-sources.yml` (`bst source track`; local elements automerge
   PR, junction bumps review-required). Renovate cannot parse `.bst`.
6. **Plymouth** — tromso: KDE Linux breeze-bgrt assets + kde-build-meta
   `core-deps/plymouth.bst` (initramfs module auto-detects). xfce-linux:
   shadows the gnomeos GNOME watermark with the libxfce4ui logo. Both add
   a bootc `kargs.d` drop-in with `splash` (never add `quiet` — CI serial
   assertions need boot text).

## Landmines

- One root `Justfile` only; extra recipes go in `iso.justfile` + `import`.
  just ≥1.30 hard-errors on `justfile`+`Justfile` ambiguity → all CI dies.
- Changing `project.conf` `name:` (or anything global) invalidates every
  BuildStream cache key → one full world rebuild (~6 h chunk jobs).
- `.gitignore` with unanchored `Containerfile` silently drops
  `<target>/Containerfile`.
- Keep `install-flatpaks.sh` and `configure-live.sh` on the **same**
  installer app ID; they drifted apart once and the installer never launched.
- New workflow files can't be `gh workflow run` until merged to the default
  branch.
- track-sources PRs made with `GITHUB_TOKEN` don't trigger CI; set
  `BOT_TOKEN` secret for automerge to work.

## Dakota study (2026-07-19) — adopted vs deferred

Adopted: track-bst-sources, LUKS e2e + screenshots, promote/rollback-stable
(rollback is dispatch-only, dry_run-default, digest-preserving skopeo retag
+ branch force-push), renovate-config-validator lint job. Principles worth
keeping: smoke tests live in a *separate* workflow chained via workflow_run
(a reusable-call job can't be continue-on-error, so inline smoke reddens
the publish pipeline); promotion/rollback share one concurrency group so
they can't race. Deferred with issues: security trio
(vuln-scan/CodeQL/Scorecard — tromso#87, xfce#45), aarch64 (tromso#88),
bonedigger+actionadon lifecycle bots (tromso#89), execute-release-style
GitHub Releases on promotion (noted on tromso#83). Dakota's 3-branch model
(testing trunk / main bookmark / next experimental) maps to our simpler
main=nightly + stable; `next` has no equivalent — add one only if junction
experiments need a channel.

## Guard rails & ops

Each repo's `docs/ci-and-iso-pipeline.md` has the full guard-rail chain
(required checks incl. bst graph gate + invariants tests, nightly salvage
build, boot gates, LUKS e2e, kanpur KVM validation) plus kanpur runner ops
(re-registration recipe). CI-gate rules live in each AGENTS.md — the big
three: no `paths:` filters on required-check workflows, update
branch-protection contexts when renaming required jobs, never `|| echo` a
gate. Signing is still TODO (cosign keyless — tromso#86/xfce#44, crib
RazorfinOS-org/cosmic-build-meta). Upstream watch: KDE Linux's official
BuildStream migration at invent.kde.org/packaging/kde-buildstream is
tromso's long-term junction target (tromso#85).

## Debug loop

Use the `ci-fix-loop` skill (dispatch narrow → ScheduleWakeup → diagnose
from `--log-failed` → fix → re-dispatch). Log every symptom→cause→fix row
in the repo's `docs/ci-and-iso-pipeline.md` table while iterating.
