---
name: driving-pi
description: Launch and supervise a `pi` agent session in tmux as a delegated worker — correct CLI invocation, briefing it in a file rather than a prompt, keeping two agents out of each other's way in one repo, and the babysitting loop. Use when delegating a workstream to pi, running several agents in parallel across the tuna-os repos, or when a spawned agent's messages are not landing.
---

# Driving pi

`pi` is a second agent CLI (separate from Claude Code). Delegating to it is
useful when a workstream is long, mechanical and separable — but it is an
*interactive TUI*, not a batch tool, so it needs a tmux window and periodic
supervision.

## Launching it

```bash
tmux new-window -t 0: -n <name> -c /path/to/repo
tmux send-keys -t 0:<name> 'pi --name <session-name> @BRIEF.md "First instruction."' Enter
```

**`@file` must be its own argument.** This fails:

```bash
pi "@BRIEF.md Read this first and start work."     # WRONG
# Error: File not found: /path/@BRIEF.md Read this first and start work.
```

pi takes the whole quoted string as the filename. Correct form:

```bash
pi @BRIEF.md "Read this first and start work."     # RIGHT
```

Useful flags: `--name` (display name), `-p` (non-interactive, process and
exit), `-c` (continue), `--model`, `--no-session` (ephemeral).
Pre-configured agents live in `~/.pi/agent/agents/*.md` — check for one
matching the domain before writing a brief from scratch.

## Brief in a file, not in the prompt

Write the brief to a Markdown file in the repo and pass it with `@`. A file
survives scrollback, the agent can re-read it, and you can correct it later
without retyping. A long prompt string cannot be any of those.

What a good brief carries:

- **Scope, and the boundary.** What it owns, and explicitly what it must not
  touch — branches, directories, other agents' PRs.
- **"Stop and ask" rather than "work around".** Say this outright. An agent
  that routes around a boundary silently is worse than one that blocks.
- **Traps already paid for.** Every trap you hand over is a cycle it does not
  spend. This is the highest-value part of the brief.
- **Definition of done**, with the exact command that proves it.
- **What is already done** — a "do not redo" list.

## Two agents in one repository

Give each a **non-overlapping slice**, in writing, in both briefs. Splitting
by *area* works (CI/infrastructure vs. content; engine vs. manifests);
splitting by *file* does not survive contact.

Tell each agent that the other exists, what it owns, and to report a
boundary collision to you rather than racing. Then sequence them so one's
output validates the other's — a gate landing before the recipes it will
check is worth more than both finishing at once.

> **Fleet-level concerns — reading session state, recovering a wedged
> session, resuming by ID, splitting work between agents, durability — live in
> `tmux-agent-fleet`. This file covers what is specific to `pi`.**

## Keystrokes do not always land

**This is the failure that silently wastes the most time.** A multi-line
`send-keys` payload is delivered as a bracketed paste, and the trailing
`Enter` is absorbed into the paste rather than submitting it. The message
sits in the prompt buffer, staged and unsent, looking delivered.

Symptom, visible in `capture-pane`:

```
❯ [Pasted text #1 +1 lines]
```

Fixes, in order of reliability:

1. **Send one line per `send-keys` call**, each with its own `Enter`.
2. Send a bare `Enter` afterwards to flush anything staged.
3. Always verify with `capture-pane` that the prompt is empty.

```bash
# Reliable: line at a time
for line in "First point." "Second point."; do
  tmux send-keys -t 0:<name> "$line" Enter; sleep 1
done
tmux capture-pane -t 0:<name> -p | tail -3     # confirm it went
```

A busy agent queues input rather than submitting it, so a single `Enter` may
need repeating.

## The babysitting loop

```bash
tmux capture-pane -t 0:<name> -p -S -50 | grep -vE '^\s*$' | tail -15
```

Read for four things:

- **A question waiting on you.** Answer it with data, not opinion — check
  the branch protection, read the config, then reply.
- **A stale wait.** Agents wait on cancelled CI runs forever. A run
  superseded by concurrency keeps reporting `pending` in `gh pr checks` and
  will never complete. Verify the run is alive before letting an agent
  block on it.
- **A false permanent constraint.** "X is impossible on Y" is usually "X is
  not wired up for Y yet". Check before it gets written into a manifest
  comment or a PR body.
- **Drift across the boundary.**

Intervene early on conventions — the first recipe or first commit sets the
pattern for everything after it.

## Correct yourself out loud

When you hand an agent something wrong, send the correction with the same
weight as the original, and say plainly that you were wrong. Agents write
your claims into commit messages and PR bodies, where they outlive the
session. A wrong reason that ships is worse than no reason.

State the *narrower true* version rather than just retracting: "declared but
never exercised — zero cells in the gate matrix" is actionable, "not a
target" was not.

## When not to use pi

- One-shot mechanical edits — do them yourself, faster.
- Anything needing your conversation context — a fresh agent does not have
  it, and the brief is a lossy channel.
- Work that must land in a specific PR someone else is editing.
