#!/usr/bin/env bash
# hive-fork-switch.sh — retire the fork onto a stock upstream image when that is
# genuinely safe, and bring the fork back the moment it is not.
#
# WHY A CONTROLLER AND NOT A BUTTON
# ---------------------------------
# "Upstream merged our feature" is necessary and nowhere near sufficient. The
# first manual attempt at this swap took hive-reef DOWN for two minutes, and
# the capability check was perfectly correct at the time: upstream v4 really
# does ship branding.go with HIVE_BRANDING_CSS/HIVE_BRANDING_JSON. The image
# still could not run here.
#
#   Failed to pull … no match for platform in manifest
#
# ghcr.io/kubestellar/hive:latest publishes linux/arm64 ONLY; these nodes are
# amd64. Our fork's docker.yml commit — the one that looks like a throwaway
# "push to our own org" tweak — is what builds the amd64 image the fleet
# actually runs on. A capability-only gate would have swapped us into that
# outage automatically, every time, and the deployment uses strategy Recreate,
# so the old pod is gone BEFORE the new one is proven.
#
# So every gate below is a thing that has already gone wrong once.
#
# GATES (all must pass, in order, before anything is changed)
#   1. capability   the AI check has said MERGED_EQUIVALENT on the last TWO
#                   runs. One model call must not have authority over the
#                   production image.
#   2. candidate    an upstream image exists that is on the tracked branch AND
#                   contains the capability AND publishes an image for THIS
#                   cluster's node architecture. Resolved to a DIGEST; `latest`
#                   is never used as a deploy reference because it moves and,
#                   right now, it moves to something unrunnable.
#   3. config       the branding files the upstream mechanism reads are present
#                   on the data volume — /data/branding/custom.css and
#                   branding.json. Without them a "successful" swap silently
#                   serves stock Hive with bees on it.
#   4. cooldown     no rollback in the last COOLDOWN_DAYS. A fleet that flaps
#                   between images is worse than one that stays on the fork.
#
# AFTER THE SWAP the page is verified BY CONTENT, not by status code:
# /branding/custom.css returns 401 unauthenticated, so "not an error" passes on
# a completely unbranded dashboard. We assert our own marks are present in the
# served index. Anything less and the check certifies the wrong thing.
#
# ROLLBACK is to the recorded DIGEST we came from — never a tag, which may have
# moved since. It is automatic, immediate, and it starts a cooldown.
#
# "BRING BACK AS NEEDED" is not only a post-swap concern: `verify` runs on the
# same schedule against whatever is deployed, so an upstream image that
# regresses branding three weeks later is caught and reverted too.
#
# USAGE
#   hive-fork-switch.sh status          # gates + current state, changes nothing
#   hive-fork-switch.sh verify          # content-check the running deployment,
#                                       # roll back to the fork if it fails
#   hive-fork-switch.sh reconcile       # evaluate gates; swap or revert
#
# Env:
#   HIVE_FORK_SWITCH_DRYRUN=1  evaluate and print; never mutate
#   HIVE_FORK_SWITCH_NS        single namespace (default: both hives)

set -u

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
else
  unset KUBECONFIG
fi

NAMESPACES="${HIVE_FORK_SWITCH_NS:-hive-reef hive}"   # reef first: if it breaks, school still serves
LABEL=app.kubernetes.io/name=hive
STATE_DIR="${HIVE_ROTATE_STATE:-$HOME/.local/state/hive-rotate}"
VERDICTS="$STATE_DIR/fork-ai-verdicts.tsv"
SWITCH_STATE="$STATE_DIR/fork-switch.tsv"      # ns <TAB> mode <TAB> fork_digest <TAB> ts
COOLDOWN_FILE="$STATE_DIR/fork-switch-cooldown"
COOLDOWN_DAYS="${HIVE_FORK_SWITCH_COOLDOWN_DAYS:-7}"
UPSTREAM_REPO=kubestellar/hive
FORK_IMAGE_REPO=ghcr.io/tuna-os/hive
DRY="${HIVE_FORK_SWITCH_DRYRUN:-0}"
mkdir -p "$STATE_DIR"; touch "$SWITCH_STATE"

ACTION="${1:-status}"
case "$ACTION" in status|verify|reconcile) ;; *) echo "usage: $0 status|verify|reconcile" >&2; exit 2 ;; esac

pod_of() { kubectl get pods -n "$1" -l "$LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null; }
say() { printf '%s\n' "$*"; }

# ── Gate 1: capability, stable across two runs ──────────────────────────
capability_ok() {
  local last two
  last=$(awk -F'\t' '$1=="branding"{print $2}' "$VERDICTS" | tail -1)
  two=$(awk -F'\t' '$1=="branding"{print $2}' "$VERDICTS" | tail -2 | head -1)
  [ "$last" = MERGED_EQUIVALENT ] && [ "$two" = MERGED_EQUIVALENT ]
}

# ── Gate 2: a runnable candidate image ──────────────────────────────────
# Node architecture is read from the cluster, not assumed. The whole point of
# this gate is that "the image exists" and "the image runs here" are different
# questions, and only the second one matters.
node_arch() { kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}' 2>/dev/null; }

# Emits "<digest>" for an upstream tag that publishes ARCH, or nothing.
# Checked against the registry manifest list — the same source the kubelet
# consults, so a pass here means the pull will succeed.
candidate_digest() {
  local arch="$1" pod="$2" tag="$3"
  kubectl exec -n hive "$pod" -- sh -c "
    T=\$(curl -s 'https://ghcr.io/token?scope=repository:$UPSTREAM_REPO:pull&service=ghcr.io' | jq -r '.token // empty')
    [ -z \"\$T\" ] && exit 1
    M=\$(curl -s -H \"Authorization: Bearer \$T\" \
      -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json' \
      https://ghcr.io/v2/$UPSTREAM_REPO/manifests/$tag)
    printf '%s' \"\$M\" | jq -e '[.manifests[]?|select(.platform.os==\"linux\" and .platform.architecture==\"$arch\")]|length>0' >/dev/null 2>&1 || exit 1
    curl -sI -H \"Authorization: Bearer \$T\" \
      -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json' \
      https://ghcr.io/v2/$UPSTREAM_REPO/manifests/$tag \
      | tr -d '\r' | awk -F': ' '/[Dd]ocker-[Cc]ontent-[Dd]igest/{print \$2}'" 2>/dev/null
}


# The commit an image was actually built from. Named tags are not git refs, so
# this is the only exact way to ask "does THIS image carry the capability".
image_revision() {
  local pod="$1" tag="$2" arch="$3"
  kubectl exec -n hive "$pod" -- bash -c "
    T=\$(curl -s 'https://ghcr.io/token?scope=repository:$UPSTREAM_REPO:pull&service=ghcr.io' | jq -r '.token // empty')
    IDX=\$(curl -s -H \"Authorization: Bearer \$T\" -H 'Accept: application/vnd.oci.image.index.v1+json' \
            https://ghcr.io/v2/$UPSTREAM_REPO/manifests/$tag)
    A=\$(printf '%s' \"\$IDX\" | jq -r '[.manifests[]?|select(.platform.architecture==\"$arch\" and .platform.os==\"linux\")][0].digest')
    [ -z \"\$A\" ] || [ \"\$A\" = null ] && exit 1
    M=\$(curl -s -H \"Authorization: Bearer \$T\" -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
          https://ghcr.io/v2/$UPSTREAM_REPO/manifests/\$A)
    C=\$(printf '%s' \"\$M\" | jq -r '.config.digest')
    curl -sL -H \"Authorization: Bearer \$T\" https://ghcr.io/v2/$UPSTREAM_REPO/blobs/\$C \
      | jq -r '.config.Labels[\"org.opencontainers.image.revision\"] // empty'" 2>/dev/null
}

# Does the commit this image was built from contain the capability?
capability_at_commit() {
  local pod="$1" rev="$2"
  kubectl exec -n hive "$pod" -- bash -c "
    PEM=/secrets/gh-app-key.pem
    B64() { openssl base64 -e -A | tr '+/' '-_' | tr -d '='; }
    NOW=\$(date +%s)
    H=\$(printf '%s' '{\"alg\":\"RS256\",\"typ\":\"JWT\"}' | B64)
    P=\$(printf '%s' \"{\\\"iat\\\":\$((NOW-60)),\\\"exp\\\":\$((NOW+540)),\\\"iss\\\":\\\"\$GH_APP_ID\\\"}\" | B64)
    S=\$(printf '%s.%s' \"\$H\" \"\$P\" | openssl dgst -sha256 -sign \$PEM | B64)
    T=\$(curl -s -X POST -H \"Authorization: Bearer \$H.\$P.\$S\" https://api.github.com/app/installations/\$GH_APP_INSTALLATION_ID/access_tokens | jq -r '.token // empty')
    # -L is required: this endpoint answers 301 for this repo (kubestellar/hive
    # now redirects to hivecommons/hive), and a bare status check reads a
    # redirect as file-absent -- which made the gate report that v4 HEAD lacks a
    # capability it demonstrably has. No quote characters in this comment: it
    # lives inside a double-quoted string passed to bash -c, and an unescaped
    # quote here silently breaks the whole exec (it returned empty, which the
    # caller then read as not-200).
    curl -sL -o /dev/null -w '%{http_code}' -H \"Authorization: token \$T\" \
      'https://api.github.com/repos/$UPSTREAM_REPO/contents/src/pkg/dashboard/branding.go?ref=$rev'" 2>/dev/null
}

# ── Gate 3: the config the upstream mechanism reads ─────────────────────
branding_files_present() {
  local ns="$1" pod; pod=$(pod_of "$ns"); [ -n "$pod" ] || return 1
  kubectl exec -n "$ns" "$pod" -- sh -c \
    '[ -s /data/branding/custom.css ] && [ -s /data/branding/branding.json ]' >/dev/null 2>&1
}

# ── Gate 4: cooldown ────────────────────────────────────────────────────
in_cooldown() {
  [ -s "$COOLDOWN_FILE" ] || return 1
  local then now
  then=$(cat "$COOLDOWN_FILE" 2>/dev/null); now=$(date +%s)
  [ -n "$then" ] && [ $(( (now - then) / 86400 )) -lt "$COOLDOWN_DAYS" ]
}

# ── Content verification ────────────────────────────────────────────────
# Asserts OUR marks in the SERVED page. A 200 proves the server is up; it does
# not prove the page is ours, and those are different failures.
branding_renders() {
  local ns="$1" pod sid marks out
  pod=$(pod_of "$ns"); [ -n "$pod" ] || return 1
  sid=$(kubectl exec -n "$ns" "$pod" -- cat /data/dashboard-sessions.json 2>/dev/null \
        | jq -r 'to_entries|map(select(.value.Role=="owner"))|sort_by(.value.ExpiresAt)|reverse|.[0].key // empty')
  [ -n "$sid" ] || return 1
  marks=$(kubectl exec -n "$ns" "$pod" -- sh -c \
            'jq -r "[.product_name, .mark, .title] | @tsv" /data/branding/branding.json 2>/dev/null')
  [ -n "$marks" ] || return 1
  out=$(kubectl exec -n "$ns" "$pod" -- sh -c \
          "curl -s --max-time 30 -H 'Cookie: hive_session=$sid' http://127.0.0.1:3002/ | head -c 2000000" 2>/dev/null)
  [ -n "$out" ] || return 1
  local pn mk
  pn=$(printf '%s' "$marks" | cut -f1); mk=$(printf '%s' "$marks" | cut -f2)
  printf '%s' "$out" | grep -qF "$pn" || return 1
  printf '%s' "$out" | grep -qF "$mk" || return 1
  return 0
}

# Returns: 0 healthy, 1 measured UNHEALTHY, 2 COULD NOT MEASURE.
#
# The third case is not pedantry. On its first in-cluster run this script could
# not read Deployments (missing RBAC), so every hive looked unhealthy and, had
# any been in upstream mode, it would have rolled back a perfectly good fleet on
# a permissions error. An unreadable cluster must never be mistaken for a broken
# one -- the same unmeasured-is-not-evidence rule the rotation probes use.
healthy() {
  local ns="$1" pod ready code
  pod=$(pod_of "$ns"); [ -n "$pod" ] || return 2
  ready=$(kubectl get deploy hive -n "$ns" -o jsonpath='{.status.readyReplicas}' 2>/dev/null) || return 2
  [ -n "$ready" ] || return 2
  [ "$ready" = 1 ] || return 1
  code=$(kubectl exec -n "$ns" "$pod" -- curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
           http://127.0.0.1:3002/api/health 2>/dev/null)
  [ -z "$code" ] && return 2
  [ "$code" = 200 ] || return 1
  # readyReplicas and /api/health prove the SERVER is up; they say nothing about
  # whether the hive does any work. An image that boots cleanly and then cannot
  # launch a single agent would pass both and be accepted. Require that some
  # agents are actually working before calling an image good.
  #
  # Agents relaunch on any image change, so this is only meaningful after they
  # have had time to come up -- callers sleep before the post-swap check, and a
  # transient zero reads as UNKNOWN (2), never as a failure, so a slow start
  # cannot trigger a rollback on its own.
  local tok working
  tok=$(kubectl get secret -n "$ns" hive-secrets -o jsonpath='{.data.HIVE_DASHBOARD_TOKEN}' 2>/dev/null | base64 -d)
  [ -n "$tok" ] || return 2
  working=$(kubectl exec -n "$ns" "$pod" -- curl -sS -H "X-Hive-Internal: $tok" --max-time 25 \
              http://127.0.0.1:3002/api/status 2>/dev/null \
            | jq -r '[.agents[]?|select(.busy=="working")]|length' 2>/dev/null)
  [ -n "$working" ] || return 2
  [ "$working" -ge "${HIVE_FORK_SWITCH_MIN_WORKING:-3}" ] || return 2
  return 0
}

record_mode() {
  grep -v "^$1	" "$SWITCH_STATE" > "$SWITCH_STATE.tmp" 2>/dev/null || true
  printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$SWITCH_STATE.tmp"
  mv "$SWITCH_STATE.tmp" "$SWITCH_STATE"
}
mode_of()        { awk -F'\t' -v n="$1" '$1==n{print $2}' "$SWITCH_STATE" | tail -1; }
fork_digest_of() { awk -F'\t' -v n="$1" '$1==n{print $3}' "$SWITCH_STATE" | tail -1; }

rollback() {
  local ns="$1" to="$2" why="$3"
  say "  !! ROLLBACK $ns -> $to  ($why)"
  [ "$DRY" = 1 ] && { say "     (dry run)"; return 0; }
  kubectl -n "$ns" set image deploy/hive "hive=$to" >/dev/null 2>&1
  kubectl -n "$ns" rollout status deploy/hive --timeout=420s >/dev/null 2>&1
  date +%s > "$COOLDOWN_FILE"
  record_mode "$ns" fork "$to"
  say "     rolled back; ${COOLDOWN_DAYS}d cooldown started"
}

# ── verify: content-check whatever is deployed, revert if it lies ───────
do_verify() {
  local ns="$1" cur mode fd
  cur=$(kubectl -n "$ns" get deploy hive -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
  mode=$(mode_of "$ns"); fd=$(fork_digest_of "$ns")
  say "  $ns: image=$cur mode=${mode:-unknown}"
  healthy "$ns"; local hs=$?
  if [ $hs -eq 2 ]; then
    say "    health UNKNOWN (could not read cluster state) — no action"
    return
  fi
  if [ $hs -eq 1 ]; then
    say "    unhealthy"
    [ "$mode" = upstream ] && [ -n "$fd" ] && rollback "$ns" "$fd" "unhealthy on upstream image"
    return
  fi
  if branding_renders "$ns"; then
    say "    branding renders (product name + mark present in served index)"
  else
    say "    branding NOT rendering"
    # Only a revert-worthy fault when we put it on upstream. On the fork the
    # strings were never applied anyway (the fork ships CSS branding only), so
    # reverting would fix nothing and would only churn the deployment.
    [ "$mode" = upstream ] && [ -n "$fd" ] && rollback "$ns" "$fd" "branding regressed on upstream image"
  fi
}

# ── Run ─────────────────────────────────────────────────────────────────
ARCH=$(node_arch); HPOD=$(pod_of hive)
if [ -z "$ARCH" ]; then
  echo "ERROR: could not read node architecture (RBAC on nodes?). Gate 2 is meaningless" >&2
  echo "       without it, and a blank arch matches no manifest, so refusing to run." >&2
  exit 1
fi
say "hive-fork-switch ($ACTION)  nodes=$ARCH  cooldown=$(in_cooldown && echo ACTIVE || echo clear)"
say

if [ "$ACTION" = verify ]; then
  for ns in $NAMESPACES; do do_verify "$ns"; done
  exit 0
fi

# Gate 1
if capability_ok; then say "gate1 capability : PASS (MERGED_EQUIVALENT twice)"
else say "gate1 capability : HOLD (need two consecutive MERGED_EQUIVALENT; latest=$(awk -F'\t' '$1=="branding"{print $2}' "$VERDICTS" | tail -1 || echo none))"; fi

# Gate 2 — the one that would have prevented the outage.
#
# CANDIDATE TAGS ARE NAMED FIRST, and getting this wrong cost a wrong
# conclusion once already. An earlier version scanned only sha-shaped tags
# (^[0-9a-f]{7,40}$) and concluded "no upstream image is both amd64 and carries
# the capability" -- while `stable` and `v4-latest` were sitting there,
# multi-arch, built from v4 HEAD. The upstream docs tell operators to use
# `stable`, so that is the tag to try first; `latest` is deliberately NOT in
# this list because it is the one tag currently published arm64-only.
#
# Capability is checked against the image's OWN revision label
# (org.opencontainers.image.revision) rather than the tag name, because
# `stable` is not a git ref and cannot be passed to the contents API. This also
# makes the check exact: we ask whether the commit THIS IMAGE WAS BUILT FROM
# carries the capability, not whether some branch does.
CAND=""; CAND_TAG=""; CAND_REV=""
for tag in stable v4-latest; do
  d=$(candidate_digest "$ARCH" "$HPOD" "$tag")
  [ -n "$d" ] || { say "  gate2: $tag has no linux/$ARCH image"; continue; }
  rev=$(image_revision "$HPOD" "$tag" "$ARCH")
  [ -n "$rev" ] || { say "  gate2: $tag has no revision label"; continue; }
  has=$(capability_at_commit "$HPOD" "$rev")
  [ "$has" = 200 ] || { say "  gate2: $tag (rev ${rev:0:8}) does not carry the capability"; continue; }
  CAND="ghcr.io/$UPSTREAM_REPO@$d"; CAND_TAG="$tag"; CAND_REV="$rev"; break
done
if [ -n "$CAND" ]; then say "gate2 candidate  : PASS  $CAND_TAG (rev ${CAND_REV:0:8}) -> $CAND"
else say "gate2 candidate  : HOLD (no upstream image is both linux/$ARCH AND carries the capability)"; fi

# Gate 4
if in_cooldown; then say "gate4 cooldown   : HOLD (rollback within ${COOLDOWN_DAYS}d)"
else say "gate4 cooldown   : PASS"; fi
say

for ns in $NAMESPACES; do
  b=$(branding_files_present "$ns" && echo PASS || echo HOLD)
  say "gate3 config $ns : $b"
done
say

[ "$ACTION" = status ] && exit 0

# ── reconcile ───────────────────────────────────────────────────────────
if ! capability_ok || [ -z "$CAND" ] || in_cooldown; then
  say "holding: not all gates pass — staying on the fork (this is the safe state, not a failure)"
  for ns in $NAMESPACES; do do_verify "$ns"; done
  exit 0
fi

for ns in $NAMESPACES; do
  branding_files_present "$ns" || { say "  $ns: skip (branding files missing)"; continue; }
  cur=$(kubectl -n "$ns" get deploy hive -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
  case "$cur" in *"$UPSTREAM_REPO"*) say "  $ns: already upstream"; do_verify "$ns"; continue;; esac
  # Record the digest we are leaving, resolved from the RUNNING pod so rollback
  # targets something we know pulled on this cluster.
  curdig=$(kubectl -n "$ns" get pod -l "$LABEL" -o jsonpath='{.items[0].status.containerStatuses[0].imageID}' 2>/dev/null)
  [ -n "$curdig" ] || { say "  $ns: skip (cannot resolve current digest for rollback)"; continue; }
  say "  $ns: $cur -> $CAND   (rollback digest: $curdig)"
  [ "$DRY" = 1 ] && { say "     (dry run)"; continue; }
  record_mode "$ns" upstream "$curdig"
  kubectl -n "$ns" set image deploy/hive "hive=$CAND" >/dev/null 2>&1
  if ! kubectl -n "$ns" rollout status deploy/hive --timeout=420s >/dev/null 2>&1; then
    rollback "$ns" "$curdig" "rollout did not become ready"; continue
  fi
  # Agents relaunch on an image change and take minutes, not seconds. Judging
  # once at 45s would roll back a perfectly good image for being slow.
  say "     waiting for agents to relaunch before judging the image"
  for _i in $(seq 1 20); do
    sleep 30
    healthy "$ns" && break
  done
  healthy "$ns"; hs=$?
  if [ $hs -ne 0 ]; then
    rollback "$ns" "$curdig" "$([ $hs -eq 2 ] && echo 'could not confirm health after swap' || echo 'unhealthy after swap')"
    continue
  fi
  if ! branding_renders "$ns"; then rollback "$ns" "$curdig" "branding absent from served page"; continue; fi
  say "     upstream image verified: healthy and branded"
done
