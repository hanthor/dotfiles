#!/usr/bin/env bash
# hive-fork-ai-check.sh — has upstream grown what our fork carries, IN SOME FORM?
#
# WHY THIS EXISTS ALONGSIDE hive-fork-drift.sh
# --------------------------------------------
# hive-fork-drift.sh asks a GIT question: is our branch still ahead, and are the
# specific PR numbers we opened merged? That is exact-identity matching and it
# has a blind spot that gets worse over time:
#
#   Our branding PR (#5690) was CLOSED, not merged. If upstream later ships
#   operator branding by a DIFFERENT mechanism — a theme config, a template
#   hook, a --branding-file flag — then our PR stays closed forever, our branch
#   stays ahead forever, and a commit-identity check keeps reporting "still
#   needed" while the reason to maintain a fork has quietly evaporated.
#
# So this asks the CAPABILITY question instead: "can an operator do X on stock
# upstream today?" That is a judgement about equivalent functionality, not a
# diff, which is why it is worth spending an AI call on.
#
# WHY NOT MATCH ON FILE PATHS
# ---------------------------
# The obvious implementation — fetch upstream's copy of each file we patch and
# compare — fails on exactly the case that matters. src/pkg/dashboard/branding.go
# does not exist upstream and never will if upstream solves it elsewhere, so a
# path-based check returns "absent" every week: the right answer today, and it
# stays "right" straight past the day it becomes wrong. The prompt therefore
# describes the capability and hands the model upstream's CURRENT dashboard
# surface to look for any equivalent, wherever it lives.
#
# WHAT IS AND IS NOT WATCHED
# --------------------------
# Only items that COULD land upstream are worth an AI call. Our other fork
# commit patches .github/workflows/docker.yml to push images to our own org —
# that is fork-local by construction and will never be upstreamed, so it is a
# static note, not a question. It does matter for the conclusion though: it is
# the last thing pinning us to a fork BUILD once branding lands, so a merged
# verdict means "retire the fork IF you also move to the upstream image plus
# config", never a bare "retire the fork".
#
# NEVER AUTO-ACTS. A MERGED_EQUIVALENT verdict produces a Discord message and
# nothing else. Retiring the fork means an image swap with a branding
# regression behind it — a human decision.
#
# USAGE
#   hive-fork-ai-check.sh check
#
# Env:
#   HIVE_FORK_AI_DRYRUN=1   evaluate and print, never post to Discord

set -u

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

NS="${HIVE_NS:-hive}"
LABEL=app.kubernetes.io/name=hive
STATE_DIR="${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}"
VERDICTS="$STATE_DIR/fork-ai-verdicts.tsv"
UPSTREAM_REPO=kubestellar/hive
FORK_REPO=tuna-os/hive
FORK_BRANCH="${HIVE_FORK_AI_BRANCH:-build/tunaos-branding}"
UPSTREAM_BRANCH="${HIVE_FORK_AI_UPSTREAM_BRANCH:-v4}"
mkdir -p "$STATE_DIR"
touch "$VERDICTS"

ACTION="${1:-check}"
case "$ACTION" in check) ;; *) echo "usage: $0 check" >&2; exit 2 ;; esac

POD=$(kubectl get pods -n "$NS" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$POD" ] || { echo "ERROR: no hive pod in $NS" >&2; exit 1; }

# GitHub via curl + a minted App token, NOT `gh`. The ops image has no gh at
# all — hive-fork-drift.sh still calls `gh api` and has therefore been printing
# "could not look up" for both tracked PRs since it moved in-cluster, silently
# never firing its merged-alert. Same conversion hive-metrics.sh already got.
gh_get() {
  kubectl exec -n "$NS" "$POD" -- sh -c "
    PEM=/secrets/gh-app-key.pem
    APP_ID=\${GH_APP_ID:-}
    INST_ID=\${GH_APP_INSTALLATION_ID:-}
    [ -z \"\$APP_ID\" ] || [ -z \"\$INST_ID\" ] && exit 1
    B64() { openssl base64 -e -A | tr '+/' '-_' | tr -d '='; }
    NOW=\$(date +%s)
    H=\$(printf '%s' '{\"alg\":\"RS256\",\"typ\":\"JWT\"}' | B64)
    P=\$(printf '%s' \"{\\\"iat\\\":\$((NOW-60)),\\\"exp\\\":\$((NOW+540)),\\\"iss\\\":\\\"\$APP_ID\\\"}\" | B64)
    S=\$(printf '%s.%s' \"\$H\" \"\$P\" | openssl dgst -sha256 -sign \$PEM | B64)
    T=\$(curl -s -X POST -H \"Authorization: Bearer \$H.\$P.\$S\" \
          https://api.github.com/app/installations/\$INST_ID/access_tokens | jq -r '.token // empty')
    [ -z \"\$T\" ] && exit 1
    curl -s --max-time 30 -H \"Authorization: token \$T\" -H 'Accept: application/vnd.github+json' \
      \"https://api.github.com$1\"" 2>/dev/null
}

# ── What we still carry ─────────────────────────────────────────────────
CMP=$(gh_get "/repos/$UPSTREAM_REPO/compare/$UPSTREAM_BRANCH...${FORK_REPO%%/*}:${FORK_REPO##*/}:$FORK_BRANCH")
AHEAD=$(printf '%s' "$CMP" | jq -r '.ahead_by // "?"')
BEHIND=$(printf '%s' "$CMP" | jq -r '.behind_by // "?"')
FILES=$(printf '%s' "$CMP" | jq -r '[.files[]?.filename] | join(", ")' 2>/dev/null)
echo "fork $FORK_REPO@$FORK_BRANCH vs $UPSTREAM_REPO@$UPSTREAM_BRANCH:"
echo "  $AHEAD commit(s) ahead, $BEHIND behind"
echo "  files: ${FILES:-none}"
echo

# Upstream's CURRENT dashboard surface — the haystack the model searches for an
# equivalent, since our own file paths are guaranteed not to exist there.
UPSTREAM_TREE=$(gh_get "/repos/$UPSTREAM_REPO/contents/src/pkg/dashboard?ref=$UPSTREAM_BRANCH" \
                | jq -r '[.[]?.name] | join(" ")' 2>/dev/null)

# ── Ask ─────────────────────────────────────────────────────────────────
# One capability, described in operator terms. The model is told explicitly
# that an equivalent may live anywhere and that "not at this path" is not an
# answer — that is the failure mode this whole script exists to avoid.
# The prompt is streamed into a file inside the pod and read back with $(cat),
# rather than interpolated into the `kubectl exec … sh -c "…"` string. The
# inline form has three levels of quoting (local shell, kubectl's sh -c, then
# claude's argument) and the prompt contains newlines, quotes and pipes — it
# silently produced an empty reply, which the caller then correctly recorded as
# UNKNOWN. Passing it as data instead of as shell syntax removes the whole
# class of problem.
ask_ai() {
  local capability="$1" evidence="$2" out
  cat <<PROMPT | kubectl exec -i -n "$NS" "$POD" -- sh -c 'cat > /data/home/.fork-ai-prompt.txt && chmod 644 /data/home/.fork-ai-prompt.txt' 2>/dev/null
You are auditing whether a downstream fork still needs to exist.

CAPABILITY THE FORK CARRIES:
$capability

UPSTREAM EVIDENCE (current $UPSTREAM_REPO@$UPSTREAM_BRANCH):
$evidence

Question: does upstream provide this capability TODAY, in ANY form? An
equivalent may be implemented by a completely different mechanism, in a
different file, under a different name (a theme config, a template hook, a
CLI flag, an env var, a plugin point). 'There is no file at our path' is NOT
evidence of absence — judge the capability, not the diff.

Reply with EXACTLY two lines and nothing else:
VERDICT: MERGED_EQUIVALENT | PARTIAL | ABSENT
REASON: <one sentence, naming the upstream mechanism if you found one>
PROMPT
  out=$(kubectl exec -n "$NS" "$POD" -- su -s /bin/sh hive-guide -c \
          'cd /tmp && HOME=/data/home timeout 240 claude -p "$(cat /data/home/.fork-ai-prompt.txt)" 2>&1' 2>/dev/null)
  kubectl exec -n "$NS" "$POD" -- rm -f /data/home/.fork-ai-prompt.txt >/dev/null 2>&1
  printf '%s' "$out"
}

# ── Items ───────────────────────────────────────────────────────────────
# Only genuinely upstreamable capabilities get an AI call.
ITEM_KEY=branding
ITEM_CAP="An operator can re-brand the hive dashboard WITHOUT rebuilding the image:
override the product name and other user-visible strings, and override the
colour palette, supplying them at deploy time. Downstream we implement it by serving an operator-supplied stylesheet and
substituting markup-anchored strings. Do NOT assume upstream uses the same file
names -- our internal paths are irrelevant to you and must never be cited as
upstream evidence. Upstream PR #5690 proposed this and was CLOSED without
merging."
ITEM_EVID="Files currently in upstream src/pkg/dashboard/: ${UPSTREAM_TREE:-(could not list)}
Our fork is $AHEAD commit(s) ahead touching: ${FILES:-unknown}"

# No evidence, no question. An empty tree listing means the GitHub fetch failed,
# and a model asked to judge upstream with nothing to look at will invent
# something plausible rather than say "I cannot tell".
if [ -z "$UPSTREAM_TREE" ]; then
  echo "  $ITEM_KEY: UNKNOWN — could not list upstream dashboard files; not asking the model on no evidence"
  exit 0
fi

RAW=$(ask_ai "$ITEM_CAP" "$ITEM_EVID")
VERDICT=$(printf '%s' "$RAW" | grep -oE 'VERDICT:[[:space:]]*(MERGED_EQUIVALENT|PARTIAL|ABSENT)' | head -1 | awk '{print $2}')
REASON=$(printf '%s' "$RAW" | grep -oE 'REASON:.*' | head -1 | sed 's/^REASON:[[:space:]]*//' | cut -c1-300)

# An unavailable or unparseable model is UNKNOWN, never a verdict. Anthropic
# exhaustion, a wedged pane or a truncated reply must not read as ABSENT (which
# would say "keep forking" forever) or as MERGED (which would say "retire the
# fork" on no evidence). Three separate times this session an unmeasured thing
# got treated as a measurement; not here.
if [ -z "$VERDICT" ]; then
  echo "  $ITEM_KEY: UNKNOWN — model unavailable or reply unparseable; keeping previous verdict"
  PREV=$(awk -F'\t' -v k="$ITEM_KEY" '$1==k{print $2}' "$VERDICTS" | tail -1)
  echo "  previous verdict: ${PREV:-none}"
  exit 0
fi

echo "  $ITEM_KEY: $VERDICT — $REASON"

# ── Verify the verdict before believing it ──────────────────────────────
# A MERGED_EQUIVALENT verdict retires a fork, so it is the one answer that must
# never be taken on trust. On its first live run this model returned
# MERGED_EQUIVALENT and cited "upstream already ships branding.go ...
# custom_style_sanitize_test.go, csp_style_src_test.go" — none of which exist
# upstream (branding.go returns 404). It had been handed upstream's real file
# list and still echoed our own downstream paths back as if they were upstream's.
#
# So: every filename the model cites is checked against the tree we actually
# fetched. A verdict whose evidence is not in the input is not a verdict, it is
# a guess, and it degrades to UNKNOWN — which keeps the previous state and
# alerts nobody. Cheap, deterministic, and it catches precisely the failure that
# would otherwise read as "you can stop maintaining your fork now".
if [ "$VERDICT" = MERGED_EQUIVALENT ]; then
  CITED=$(printf '%s' "$REASON" | grep -oE '[A-Za-z0-9_/.-]+\.(go|js|css|yaml|yml|md)' | sort -u)
  UNSUPPORTED=""
  for f in $CITED; do
    base=$(basename "$f")
    printf '%s' "$UPSTREAM_TREE" | tr ' ' '\n' | grep -qxF "$base" || UNSUPPORTED="$UNSUPPORTED $base"
  done
  if [ -z "$CITED" ] || [ -n "$UNSUPPORTED" ]; then
    echo "  !! verdict REJECTED — cited evidence not present upstream:${UNSUPPORTED:- (no file cited at all)}"
    echo "     upstream src/pkg/dashboard/ actually contains: $(printf '%s' "$UPSTREAM_TREE" | tr ' ' '\n' | grep -icE 'brand|theme|style' ) branding/theme/style file(s)"
    echo "  $ITEM_KEY: UNKNOWN (unverified claim) — keeping previous verdict"
    exit 0
  fi
  echo "  verdict verified: cited files exist upstream"
fi

# ── Alert only on CHANGE ────────────────────────────────────────────────
PREV=$(awk -F'\t' -v k="$ITEM_KEY" '$1==k{print $2}' "$VERDICTS" | tail -1)
printf '%s\t%s\t%s\t%s\n' "$ITEM_KEY" "$VERDICT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$REASON" >> "$VERDICTS"
tail -50 "$VERDICTS" > "$VERDICTS.tmp" && mv "$VERDICTS.tmp" "$VERDICTS"

if [ "$VERDICT" = "$PREV" ]; then
  echo "  unchanged since last check — no alert"
  exit 0
fi

case "$VERDICT" in
  MERGED_EQUIVALENT)
    MSG="🎣 fork check: upstream now appears to provide **$ITEM_KEY** in some form — $REASON

Our fork ($FORK_REPO@$FORK_BRANCH) is $AHEAD commit(s) ahead of $UPSTREAM_REPO@$UPSTREAM_BRANCH and $BEHIND behind.
NOTE: the other fork commit patches .github/workflows/docker.yml to push images to our own org and is fork-local by construction — it will never be upstreamed. So this means: the fork can retire IF the deployment also moves to the upstream image plus configuration. Verify branding still renders before switching." ;;
  PARTIAL)
    MSG="🎣 fork check: upstream has PARTIAL support for **$ITEM_KEY** — $REASON (fork still needed; worth re-reading the gap)" ;;
  *)
    MSG="🎣 fork check: **$ITEM_KEY** is still absent upstream — $REASON (fork still justified)" ;;
esac

echo
echo "$MSG"
[ "${HIVE_FORK_AI_DRYRUN:-0}" = 1 ] && { echo "(dry run — not posting)"; exit 0; }

DTOK=$(kubectl get secret -n postgres fleet-alerts -o jsonpath='{.data.DISCORD_BOT_TOKEN}' 2>/dev/null | base64 -d)
DCHAN=$(kubectl get secret -n postgres fleet-alerts -o jsonpath='{.data.DISCORD_CHANNEL}' 2>/dev/null | base64 -d)
if [ -n "$DTOK" ] && [ -n "$DCHAN" ]; then
  curl -sS -X POST -H "Authorization: Bot $DTOK" -H "Content-Type: application/json" \
    -H 'User-Agent: TunaOS-Hive-Ops/1.0' \
    -d "$(jq -n --arg c "$MSG" '{content:$c}')" \
    "https://discord.com/api/v10/channels/$DCHAN/messages" >/dev/null \
    && echo "posted to Discord" || echo "! Discord post failed" >&2
else
  echo "! no Discord credentials (postgres/fleet-alerts) — logged only" >&2
fi
