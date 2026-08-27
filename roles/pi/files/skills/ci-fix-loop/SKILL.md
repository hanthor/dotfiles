---
name: ci-fix-loop
description: Iterate on a broken GitHub Actions workflow by dispatching narrow matrix cells, waiting for them asynchronously, diagnosing from real failure logs, and re-dispatching only the affected cells after each fix — repeating until green. Use when a fix needs real-CI verification (not just local lint/tests), the workflow is failing across multiple matrix cells, or the user says to "test in CI", "check the runs", or asks to keep iterating on a workflow until it passes.
---

# CI Fix Loop

A tight loop for driving a broken workflow to green without wasting turns on
manual polling or full-matrix dispatches. Complements `gh-poll` (use that
skill's sleep-loop only when `ScheduleWakeup` isn't available — prefer
`ScheduleWakeup` in Claude Code, since it frees the turn instead of blocking
it).

## The loop

1. **Dispatch narrow.** Pick the minimum set of matrix cells that exercise
   the changed code path — one cell per distinct backend/branch, not the
   full matrix. Example: for a fix touching both an ostree and a composefs
   install path, dispatch one cell of each, not all variant×flavor combos.

   ```bash
   gh workflow run "<name>" -R <owner>/<repo> --ref <branch> -f <input>=<value>
   ```

2. **Wait asynchronously.** Call `ScheduleWakeup` sized to the workflow's
   expected duration (check a recent successful run's timing if unsure).
   Don't poll — the harness re-invokes on the scheduled wake.

3. **On wake, check status before logs.** `gh run view <id> --json
   status,conclusion` for every dispatched run first. Only pull logs for
   runs that actually completed with `conclusion: failure`.

4. **Diagnose from real log text.** `gh run view <id> --log-failed`, then
   find the actual error line — never guess at a root cause from the
   symptom alone.

5. **Check local first, then fix.** Before pushing, run whatever local
   checks exist (shellcheck, bats, `bash -n`, linters) — catches
   syntax/regression issues for free without spending a CI round on them.

6. **Commit, push, re-dispatch only the affected cells.** Not the full
   matrix again — you already know which cells were failing.

7. **Repeat.** Expect each round to surface exactly one *new* bug that was
   masked by the previous failure — this is normal, not a sign the fix
   didn't work. A long chain of small, independent bugs is common in
   under-tested paths (live-boot environments, minimal containers,
   cross-distro packaging) where a build-time success proves nothing about
   runtime behavior.

## Recording as you go

Keep a running symptom → root cause → fix table somewhere durable (a repo
doc or memory) *while iterating*, not just at the end — it's easy to lose
track of which bug was which after 5+ rounds, and the record is valuable to
whoever touches this code path next. See
`docs/ci-troubleshooting.md` in tuna-os/tunaos for the format this proved
out on (a 13-bug chain fixing the LUKS E2E fisherman migration,
2026-07-16).

## Stopping condition

All dispatched cells show `conclusion: success`. Don't declare victory on
"no failures yet" while runs are still `in_progress`/`queued` — wait for
completion.
