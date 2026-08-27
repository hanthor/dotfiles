---
name: tmux-agent-fleet
description: Run several agent sessions in parallel tmux windows and orchestrate them — splitting work so they don't collide, reading their state correctly, recovering wedged sessions, and keeping findings durable when a session dies. Use when driving multiple Claude Code or pi sessions at once, when a session stops responding to input, or when coordinating agents across several repositories. For pi's CLI specifics see `driving-pi`.
---

# Driving an agent fleet in tmux

One window per session, one owner per area, an orchestrator that never does
the work itself. This is what it costs to keep that honest.

## Set-up that matters later

**Put the orchestrator in tmux too.** A session driven over plain SSH dies
when the connection closes, taking its monitors and schedulers with it. That
happened here and cost two rebuilds of the fleet's state.

**One window per session, named for its area** (`parity`, `engine`,
`bootproof`). The window name is how you address it forever after.

**A durable status file the orchestrator owns**, e.g.
`ORCHESTRATOR-STATUS.md`: the scoreboard, the per-session goal, the standing
rules. Sessions report deltas to the orchestrator rather than editing it, so
there is no write race. Say in the file that it dies with the session, and
keep an index of filed issues at the bottom — see *Durability* below.

## Reading session state: three states, not two

| state | how it looks | what to do |
|---|---|---|
| **busy** | prompt may hold text; process burning CPU | nothing — input is queued and will submit itself |
| **idle** | prompt empty, no CPU | send work |
| **staged** | visible prompt holds text or `[Pasted text #N]`; no CPU | bare `Enter` flushes it |
| **wedged** | visible prompt holds text, `Enter` does nothing, `ping` does not echo | restart it |

**Staged and wedged look identical until you press Enter.** That is the whole
diagnosis: `Enter` clears a staged prompt and the session starts working;
against a wedged one nothing happens at all, and a follow-up `ping` will not
even echo to the prompt. Never restart a session before trying `Enter` — it is
free, and staging is far more common than wedging.

**Instantaneous process CPU is the only reliable signal — and `ps pcpu` is not
it.** `pcpu` is the average over the process's whole lifetime, so a session
idle for an hour still reports the few percent it earned while working. Every
session in a stalled fleet looks identically "alive" that way. Sample the
CPU-time delta from `/proc` instead:

```bash
bash -c '
read_t(){ awk "{print \$14+\$15}" /proc/$1/stat 2>/dev/null; }   # utime+stime
declare -A A
for w in <windows>; do
  k=$(pgrep -P "$(tmux display-message -t 0:$w -p "#{pane_pid}")" | head -1)
  A[$w]="$k $(read_t $k)"
done
sleep 8
for w in <windows>; do
  set -- ${A[$w]}; d=$(( $(read_t $1) - $2 ))
  printf "%-10s %s\n" "$w" "$([ $d -lt 3 ] && echo IDLE || echo BUSY:$d)"
done'
```

**Calibrate the threshold before trusting it.** Measured here: a session doing
real work moved **150–180 ticks** per 8-second sample, while one merely
redrawing its status line moved **3–7**. A naive `>= 3 means busy` therefore
reported the entire idle fleet as BUSY. Anything under ~20 ticks is idle; the
real gap is an order of magnitude, so pick the threshold inside it rather than
just above zero.

Note the shell aliases too: `stat` and `date -r` are shadowed here by tools
that reject their flags, so use `/usr/bin/stat` and `/bin/ls` inside these
probes.

Do **not** trust a status-line marker. Greping the pane for `esc to
interrupt` reports "idle" for sessions that are demonstrably working, because
the status line truncates when other indicators are present. That single
mistake nearly caused input to be flushed into three busy sessions.

## Sending messages

**One line per `send-keys`, each with its own `Enter`.** A multi-line payload
is delivered as a bracketed paste and the trailing `Enter` is absorbed into
it — the text sits at the prompt looking delivered and is never submitted.

**One-line-per-call reduces this but does not eliminate it.** A six-line
message sent as six separate `send-keys` calls, two seconds apart, still
collapsed into `[Pasted text #1 +4 lines]` on the receiving prompt. The longer
the message, the likelier it happens. So always verify, and prefer fewer,
denser lines over many short ones.

`[Pasted text #N +M lines]` **on the visible pane is the unambiguous staged
marker** — it is the one signal that cannot be confused with a scrollback echo,
because a submitted message never renders that way.

```bash
for line in "First point." "Second point."; do
  tmux send-keys -t 0:<window> "$line" Enter; sleep 2
done
tmux capture-pane -t 0:<window> -p | grep -E '^❯' | tail -1   # verify empty
```

**`capture-pane -S` returns scrollback, and a submitted message echoes there
with the same `❯` prefix as the live prompt.** So an old `❯ do the screenshot
change` sitting in history is indistinguishable, by grep, from input staged and
unsent. Reading scrollback echoes as staged input produced a confident,
entirely false "the whole fleet is stalled, forty minutes lost" report here —
every one of those messages had in fact been received and acted on.

Capture the **visible** pane, with no `-S` flag, and read the last `❯` on it:

```bash
tmux capture-pane -t 0:<window> -p | tail -20     # no -S: current screen only
```

Before concluding a session is wedged, prove it with a probe rather than
inference. Send a trivial message and see whether it answers:

```bash
tmux send-keys -t 0:<window> "ping" Enter; sleep 4
tmux capture-pane -t 0:<window> -p | tail -6
```

A session that answers `ping` in seconds was never stuck, and this costs one
cheap round-trip against a diagnosis that is easy to get backwards.

**Idle is not wedged.** An agent that has finished its work and is waiting
looks exactly like one that is stuck, on every signal except the probe. Idle
means *send work* — it is the fleet's normal resting state, not a fault.

`Press up to edit queued messages` at the prompt is the **healthy** state — a
busy session accepted the input and will process it. An empty prompt is also
fine. Raw text sitting on the visible prompt with no CPU is *staged*, not
wedged — press `Enter` before concluding anything worse.

Half-sent text is worse than none: a message can split mid-line and leave a
fragment that later submits as gibberish. If that happens, do not fight the
TUI — send a follow-up line beginning "ignore that fragment, real message:"
and carry on. `C-u` and `C-k` frequently will not clear it.

## Recovering a wedged session

Sessions wedge under context pressure — seen at 262.3k, 421k and 575.9k
tokens, with a `/clear to save …` hint showing beforehand. Treat that hint as
a warning.

```bash
# 1. Check nothing is at risk. Untracked scratch is fine; tracked edits are not.
cd <repo> && git status --short | grep -vE '^\?\?'
#    Check every worktree, not just the main checkout — an agent may have been
#    working in a detached one:
for d in $(git worktree list --porcelain | awk '/^worktree /{print $2}'); do
  n=$(git -C "$d" status --short | grep -vcE '^\?\?')
  [ "$n" -gt 0 ] && echo "DIRTY $d ($n)"
done

# 2. Kill it. C-c may clear the input buffer without restoring submission.
kill <pid>

# 3. Resume by SESSION ID, from summary.
claude --dangerously-skip-permissions --resume <uuid>
# then answer "1. Resume from summary" — full replay restores the context
# pressure that caused the wedge.

# 4. Re-brief from artifacts, not memory.
```

**Resume by ID, never `--continue`, when two sessions share a working
directory.** `--continue` picks the most recent session for that directory,
so two agents in one repo will both resume the same one and you silently lose
the other. Find the IDs and tell them apart by content:

```bash
find ~/.claude/projects/<encoded-path> -maxdepth 1 -name '*.jsonl' \
  -printf '%T@ %f\n' | sort -rn | head
grep -c "boot-harness" <uuid>.jsonl     # fingerprint each candidate
```

`/proc/<pid>/fd` will **not** identify the transcript — the CLI appends and
closes rather than holding it open. Fingerprint by content instead, using an
exact phrase lifted from the wedged session's visible pane.

**A routed phrase contaminates the fingerprint.** If you quoted one agent's
finding into another agent's prompt, that phrase now appears in *both*
transcripts, and grep will match the innocent one. Two tie-breakers, and they
agree in practice:

- **Occurrence count.** The originator says a phrase several times (writing it,
  then recapping it); a recipient has it once, from your message.
- **Mtime.** A wedged session *stops writing*. The stale file is the wedged
  one; the file still growing belongs to a session that is fine.

Getting this wrong means killing a healthy session and leaving the wedged one
running, so confirm both signals point the same way before the `kill`.

## Re-briefing after a restart

A restarted session has lost the conversation, not the work. Point it at
durable artifacts rather than retelling its history:

- the status file — scoreboard, its axis, standing rules
- its own notes on disk (`*-BRIEF.md`, `*-FINDINGS.md`)
- the filed issues
- **what changed while it was down** — merges, closures, and anything you did
  in its repo on its behalf, with the reason

Then hand back its own last conclusion. An agent that reads its pre-wedge
recommendation in your brief resumes in one step instead of re-deriving it.

## Two agents in one repository

Split by **area**, never by file, and put the boundary in both briefs:
CI/infrastructure vs. content; engine vs. manifests; the stack vs. new
recipes. Say "stop and ask" rather than "work around" — an agent that routes
around a boundary silently is worse than one that blocks.

Watch for the near-miss: an agent that respects "don't edit branch X" may
still *branch off* X and target it as a base, which has the same effect.

**Corrections must be stated as rules, not instances.** Naming two offending
PRs got those two fixed and the habit kept. Give the rule plus the command
that verifies it (`gh pr view <n> --json baseRefName`).

## Durability — assume every session dies

Session memory, the status file and the task list all die together. Anything
that must outlive them goes into the issue tracker, with the measured
evidence, while you still have it. Do this continuously, not at the end.

When a session hands you a finding it cannot act on — because it is wedged,
or busy, or the finding belongs elsewhere — write it into the tracker
yourself rather than holding it in conversation.

## Orchestrator discipline

- **Route, don't fix.** Findings go to the owning session. Doing the work
  yourself in someone else's repo creates conflicts they cannot see coming.
- **Merging on an owner's behalf is fine when they have said they want it and
  are busy** — take the merge, not the decision.
- **Own the consequences out loud.** If merging a ready PR conflicts three
  others, say so, give the exact fix, and offer to hold next time.
- **Verify before asserting.** Check whether a failure is pre-existing on the
  base branch before calling it a regression.
- **Watch for stale CI signals.** A run cancelled by concurrency reports
  `pending` forever; some jobs report a stale `fail` while the current run
  passed. Resolve the actual run before letting either block anything.
- **Check runner capacity** when everything seems slow. Queued-not-running is
  not a broken PR.

## Landmine

`git stash` inside a worktree operates on the **shared** stash stack of the
main checkout. A reflexive `git stash` / `git stash pop` there can pop another
branch's stash into your tree. Use a scratch commit instead.
