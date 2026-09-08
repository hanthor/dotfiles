# Capability tiers (T1/T2/T3) — what they mean and how a model gets one

A tier is a **competence floor**, not a cost band. `AGENT_TIERS` in
`hive-rotate.sh` says which floor each agent needs; rotation then moves that
agent *sideways* along its tier to whichever provider has headroom, and only
drops a tier when nothing at that level is available.

## The cutoffs

Set in `hive-tiers.sh`, on the **Artificial Analysis agentic index**:

```jq
tier: (if   .agentic >= 48 then "T1"
       elif .agentic >= 30 then "T2"
       else "T3" end)
```

| Tier | Cut | Meaning |
|---|---|---|
| T1 | agentic ≥ 48 | frontier — the models above the gap in the data |
| T2 | 30 ≤ agentic < 48 | competent working tier; most agents live here |
| T3 | agentic < 30 | cheap/degraded fallback rather than stranding |

**These are absolute-score bands, deliberately not rank positions.** Ranking
would silently promote a weak model into T1 whenever the field thinned out —
which is exactly the situation a provider outage creates, i.e. the moment you
least want it.

## Why 48 and 30

From the measured distribution the thresholds were originally cut against
(n=31, 2026-09-06): `max 58.2 · p75 48.0 · median 31.6 · p25 10.6 · min 0.9`.

- **48** is p75 *and* a real discontinuity. The frontier cluster runs
  58.2 → 48.0 continuously, and the next model below it is 44.5. The cut sits
  in a genuine gap, not in the middle of a cluster.
- **30** is roughly the median: it keeps the mid cluster in T2 and drops the
  weak tail to T3.

It also reproduces the hand-authored table's intent exactly — Opus 5 lands T1,
Sonnet 5 and GPT-5.6 Luna land T2.

## The scale trap — read before touching these numbers

**The bands are on the AA scale, not the Terminal-Bench one.** The two are not
comparable and mixing them has already broken this once: the first live run
used 60/40, lifted from the TB2.1 numbers in `hive-rotate.sh`'s built-in table
where the field runs to **89.5**. The AA agentic index tops out at **58.2**, so
`>= 60` matched *nothing*, T1 came back **empty**, and every T1 agent would have
stranded.

If you change a threshold, state which scale it is on.

## Two sources, unioned

| Source | What it is |
|---|---|
| `TIERS` in `hive-rotate.sh` | hand-authored, reasoned from Terminal-Bench 2.1 harness-paired scores |
| `$HIVE_ROTATE_STATE/tiers.tsv` | generated daily by `hive-tiers.sh` from the AA API |

The cache does **not** replace the table — they are unioned, de-duplicated on
provider+model, cache-first. A benchmark feed does not cover every provider the
fleet runs, so letting it replace the table deleted whole providers from the
ladder the moment a refresh succeeded.

A model also only appears if `provider_of` maps its creator to a CLI hive can
actually launch. Z AI's GLM-5.3-Flash (51.5) and SpaceXAI's Grok 4.6 (51.4)
score T1 today and are correctly absent: nothing here can run them.

## Current membership (cache generated 2026-09-08)

```
T1  anthropic  claude  claude-fable-5-1        58.2
T1  anthropic  claude  claude-opus-5-xhigh     55.7
T1  openai     codex   gpt-6-astra             51.6
T1  openai     codex   gpt-6-astra-xhigh       50.8
    ────────────────── T1 cut: 48 ──────────────────
T2  anthropic  claude  claude-sonnet-5         44.5
T2  meta       muse    muse-spark-1.2          44.2   (built-in rung)
T2  openai     codex   gpt-5-6-luna            42.9
T2  anthropic  claude  claude-opus-5-low       37.7
T2  openai     codex   gpt-5-5                 37.5
    ────────────────── T2 cut: 30 ──────────────────
T3  openai     codex   gpt-5-6-luna-low        18
T3  deepseek   pi      deepseek-v3-1-terminus   9
T3  openai     codex   gpt-5-mini               9
```

## Why muse-spark cannot take T1

**44.2 < 48.** It is 3.8 below the cut, and it lands between Sonnet 5 (44.5)
and GPT-5.6 Luna (42.9) — both T2. It is on the far side of the 48 → 44.5 gap
that the cut was chosen to sit in.

Two further reasons not to force it:

1. **The 44.2 is the `xhigh` variant.** AA scored "Muse Spark 1.2 (xhigh)". The
   rung runs muse's default `high` effort, so the score of what is actually
   placed is probably *below* 44.2, not above. Even running xhigh would not
   reach 48.
2. **AA scored bare `muse-spark-1.2`; the fleet runs `muse-spark-1.2-contributor`.**
   Same generation, differing in entitlement rather than weights, so the score
   is carried over — but that is an inference, not a measurement of the exact id.

Promoting it anyway would be the precise failure the absolute-score design
exists to prevent: filling an empty T1 with whatever is left when the frontier
providers are exhausted. That temptation is strongest exactly when T1 is empty,
which is when the promotion is least justified.

**When T1 is empty, T1 agents park.** That is the intended behaviour —
`architect`, `sec-check` and `strategist` pause rather than run on a model
below their floor, and resume when a provider recovers.

## Maintenance note: the bands have drifted from their own distribution

`hive-tiers.sh` states bands "MUST be derived from the feed's own
distribution". They were, once — and the feed has since moved:

| | n | max | p75 | median |
|---|---|---|---|---|
| when cut (2026-09-06) | 31 | 58.2 | **48.0** | **31.6** |
| today (2026-09-08) | 47 | 58.2 | **42.9** | **16.1** |

The feed grew by 16 models, mostly weak ones, pulling both percentiles down.
The thresholds are still hardcoded at 48/30, so they no longer equal the
percentiles they were derived from.

**This does not currently change any placement**, and the 48 cut still sits in
a real gap (58.2 → 48.0, then 44.5), so the structural justification holds even
though p75 moved. But re-deriving mechanically from today's p75 would set T1 at
42.9 and *would* promote muse-spark — which is the argument for keeping a
gap-aware human check rather than a pure percentile.

Worth revisiting if the distribution keeps shifting.

## Adding or promoting a model

1. Get its **AA agentic index** — do not estimate, and do not import a
   Terminal-Bench number.
2. Check it clears the band on the AA scale.
3. Check `provider_of` maps its creator to a launchable CLI, and that
   `hive-inventory.sh` can see the model id.
4. Note the effort variant that was scored, and pass that effort — or record
   that you did not.
