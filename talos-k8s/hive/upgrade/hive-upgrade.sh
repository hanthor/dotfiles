#!/usr/bin/env bash
# hive-upgrade.sh — keep the TunaOS Hive deployments on upstream's latest release.
#
# Upstream (github.com/hivecommons/hive) cuts several v5 releases an hour. We do
# NOT chase every one: once a day this picks the newest release, walks it through
# the fleet one target at a time (canary first), and soaks between targets.
#
#   hive-hanthor (canary, unbranded) → hive-reef (REEF) → hive (SCHOOL) → hive-hub
#
# Every rule below has already been learned the hard way (see
# hive-ops-scripts/hive-fork-switch.sh, which this supersedes):
#
#  * Deploy a DIGEST, never a moving tag. The image string is tag@digest; the
#    tag is only a label for humans.
#  * Check that every node architecture is in the image index BEFORE touching
#    anything. ghcr.io/kubestellar/hive:latest was once arm64-only and a swap
#    onto it took hive-reef down (strategy Recreate kills the old pod first).
#  * "Could not measure" is never "unhealthy". A kubectl/API/RBAC error aborts
#    the run and alerts; it never triggers a rollback. Only an observation
#    (not Ready, CrashLoopBackOff, restarts, HTTP != 200, branding missing from
#    the served page) counts as a failure.
#  * Verify content, not just status codes: branded hives must serve their own
#    product_name and mark (from /data/branding/branding.json) to an owner.
#  * Roll back to the recorded digest. The rollback target is written in the
#    SAME patch that changes the image, so no target is ever changed without a
#    recorded way back.
#  * Cooldown after a rollback; the bad version is blocklisted.
#  * Sequential with a soak: hive and hive-reef share one GitHub App
#    installation, and restarting both at once burns its rate limit on boot scans.
#
# USAGE
#   hive-upgrade.sh status              read-only: deployed vs target, blocklist, last result
#   hive-upgrade.sh run                 upgrade (DRY_RUN=1 to plan without mutating)
#   hive-upgrade.sh block VERSION       add VERSION to the blocklist
#   hive-upgrade.sh unblock VERSION     remove VERSION from the blocklist
#   hive-upgrade.sh pin VERSION         always target VERSION (also allows downgrade)
#   hive-upgrade.sh unpin               back to tracking
#
# ENV
#   TRACK=release|stable|candidate  release (default): newest non-draft,
#                     non-prerelease GitHub release matching HIVE_UPGRADE_LINE.
#                     stable/candidate: upstream's GHCR channel tags.
#   HIVE_UPGRADE_LINE  tag regex for TRACK=release (default ^v5\.)
#   HIVE_UPGRADE_PIN   overrides the pin stored in state
#   DRY_RUN=1          no mutating kubectl call, no state write, no Discord post
#   FORCE=1            ignore cooldown and the run lock
#   SOAK_SECONDS (600) SOAK_INTERVAL (60) VERIFY_ATTEMPTS (6) VERIFY_INTERVAL (30)
#   ROLLOUT_TIMEOUT (420) COOLDOWN_HOURS (20) KUBECTL_TIMEOUT (90)
#   GITHUB_TOKEN       optional; the cluster's shared egress IP usually has no
#                      anonymous GitHub API budget left (the hub spends it), in
#                      which case the github.com/…/releases/latest redirect is used
#   DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID (or DISCORD_CONFIG=projects.json with
#                      hive_ops_channel_id) to post; otherwise messages are printed
#
# EXIT  0 upgraded / nothing to do / holding   1 a target failed and was rolled back
#       2 aborted (could not measure / could not resolve / arch missing / rollback broken)

set -uo pipefail

if [ -z "${KUBERNETES_SERVICE_HOST:-}" ]; then
  : "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
  export KUBECONFIG
fi

TRACK="${TRACK:-release}"
LINE_RE="${HIVE_UPGRADE_LINE:-^v5\\.}"
UPSTREAM_REPO="${HIVE_UPSTREAM_REPO:-hivecommons/hive}"
SPOKE_REPO="${HIVE_SPOKE_REPO:-hivecommons/hive}"
HUB_REPO="${HIVE_HUB_REPO:-hivecommons/hive-hub}"
CONTRIB_REPO="${HIVE_CONTRIB_REPO:-hivecommons/hive-contributor}"
REGISTRY=ghcr.io
# ns|deployment|container|kind   (kind: spoke, branded, hub). Order matters: first is the canary.
TARGETS="${HIVE_UPGRADE_TARGETS:-hive-hanthor|hive|hive|spoke hive-reef|hive|hive|branded hive|hive|hive|branded hive-hub|hive-hub|hub|hub}"
CONTRIB_NS="${HIVE_CONTRIB_NS:-hive-contributors}"
HUB_SERVICE_PORT="${HIVE_HUB_SERVICE_PORT:-3001}"
HUB_MARK="${HIVE_HUB_MARK:-Hive}"
SPOKE_PORT=3002
STATE_NS="${HIVE_UPGRADE_STATE_NS:-hive}"
STATE_CM=hive-upgrade-state

DRY="${DRY_RUN:-0}"
FORCE="${FORCE:-0}"
SOAK_SECONDS="${SOAK_SECONDS:-600}"
SOAK_INTERVAL="${SOAK_INTERVAL:-60}"
VERIFY_ATTEMPTS="${VERIFY_ATTEMPTS:-6}"
VERIFY_INTERVAL="${VERIFY_INTERVAL:-30}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-420}"
COOLDOWN_HOURS="${COOLDOWN_HOURS:-20}"
KUBECTL_TIMEOUT="${KUBECTL_TIMEOUT:-90}"
LOCK_TTL_SECONDS="${LOCK_TTL_SECONDS:-10800}"

A_PREV=hive.tunaos.org/previous-image
A_PVER=hive.tunaos.org/previous-version
A_VER=hive.tunaos.org/version
A_AT=hive.tunaos.org/upgraded-at
A_RBF=hive.tunaos.org/rolled-back-from
A_RBAT=hive.tunaos.org/rolled-back-at

TMP=$(mktemp -d "${TMPDIR:-/tmp}/hive-upgrade.XXXXXX") || exit 2
LOCKED=0
cleanup() {
  if [ "$LOCKED" = 1 ]; then state_set running_since "" >/dev/null 2>&1 || true; fi
  rm -rf "$TMP"
}
trap cleanup EXIT

say()  { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
now_iso()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
now_epoch() { date +%s; }
or()        { if [ -n "$1" ]; then printf '%s' "$1"; else printf '%s' "${2:--}"; fi; }
short()     { local d="${1#sha256:}"; printf '%s' "${d:0:12}"; }

# ── kubectl wrappers ────────────────────────────────────────────────────────
# k: read-only. km: the ONLY path to a mutating call; under DRY_RUN it prints
# and returns success without running kubectl at all.
k()  { timeout "$KUBECTL_TIMEOUT" kubectl "$@"; }
km() {
  if [ "$DRY" = 1 ]; then
    say "    [dry-run] would run: kubectl $(printf '%s ' "$@" | head -c 700)"
    return 0
  fi
  MUTATED=1
  timeout "$KUBECTL_TIMEOUT" kubectl "$@"
}
MUTATED=0

# ── state ConfigMap (ns hive / hive-upgrade-state) ─────────────────────────
# Written with `kubectl replace` (verb update) carrying the resourceVersion we
# read, so two concurrent writers conflict instead of silently clobbering.
STATE_JSON=""
STATE_EXISTS=0
state_load() {
  local out
  if out=$(k -n "$STATE_NS" get configmap "$STATE_CM" -o json 2>"$TMP/state.err"); then
    STATE_JSON=$out; STATE_EXISTS=1; return 0
  fi
  if grep -q NotFound "$TMP/state.err"; then
    STATE_JSON=$(jq -cn --arg n "$STATE_CM" --arg ns "$STATE_NS" \
      '{apiVersion:"v1",kind:"ConfigMap",metadata:{name:$n,namespace:$ns,labels:{"app.kubernetes.io/name":"hive-upgrade"}},data:{}}')
    STATE_EXISTS=0; return 0
  fi
  warn "cannot read state configmap $STATE_NS/$STATE_CM: $(head -c 300 "$TMP/state.err")"
  return 1
}
state_get() { jq -r --arg k "$1" '.data[$k] // empty' <<<"$STATE_JSON"; }
# state_set k v [k v ...] — "" deletes the key.
state_set() {
  local args=() new out
  while [ $# -ge 2 ]; do args+=(--arg "$1" "$2"); shift 2; done
  new=$(jq -c "${args[@]}" '.data = (((.data // {}) + $ARGS.named) | with_entries(select(.value != "")))' <<<"$STATE_JSON") || return 1
  if [ "$DRY" = 1 ]; then
    say "    [dry-run] would write state: $(jq -c '.data' <<<"$new" | head -c 400)"
    STATE_JSON=$new; return 0
  fi
  if [ "$STATE_EXISTS" = 1 ]; then
    out=$(printf '%s' "$new" | k replace -f - -o json 2>"$TMP/state.err") || { warn "state write failed: $(head -c 300 "$TMP/state.err")"; return 1; }
  else
    out=$(printf '%s' "$new" | k create -f - -o json 2>"$TMP/state.err") || { warn "state create failed: $(head -c 300 "$TMP/state.err")"; return 1; }
    STATE_EXISTS=1
  fi
  STATE_JSON=$out
}
is_blocked() {  # label [digest]
  local bl; bl=$(state_get blocklist)
  [ -n "$bl" ] || return 1
  grep -Fxq -e "$1" <<<"$bl" && return 0
  [ -n "${2:-}" ] && grep -Fxq -e "$2" <<<"$bl"
}
history_add() {
  local h; h=$(printf '%s\n%s' "$(state_get history)" "$(now_iso) $*" | sed '/^$/d' | tail -n 30)
  printf '%s' "$h"
}

# ── Discord ─────────────────────────────────────────────────────────────────
# Payload built with jq only: a raw newline in hand-rolled JSON once caused
# silent 400s. Posts only on success-with-change and on failure/rollback/abort.
discord() {  # message
  local msg="$1" chan="${DISCORD_CHANNEL_ID:-}" code
  if [ -z "$chan" ] && [ -r "${DISCORD_CONFIG:-/config/projects.json}" ]; then
    chan=$(jq -r '.hive_ops_channel_id // empty' "${DISCORD_CONFIG:-/config/projects.json}" 2>/dev/null)
  fi
  jq -cn --arg c "$msg" '{content: $c, allowed_mentions: {parse: []}, flags: 4}' > "$TMP/discord.json" || { warn "could not build discord payload"; return 1; }
  if [ "$DRY" = 1 ] || [ -z "${DISCORD_BOT_TOKEN:-}" ] || [ -z "$chan" ]; then
    say "[discord$([ "$DRY" = 1 ] && echo ' dry-run' || echo ' not configured')] $(cat "$TMP/discord.json")"
    return 0
  fi
  printf 'Authorization: Bot %s\n' "$DISCORD_BOT_TOKEN" > "$TMP/discord.h"
  code=$(curl -s --max-time 20 -o "$TMP/discord.out" -w '%{http_code}' -X POST \
           -H @"$TMP/discord.h" -H 'Content-Type: application/json' \
           --data-binary @"$TMP/discord.json" "https://discord.com/api/v10/channels/$chan/messages")
  case "$code" in 2??) say "[discord] posted";; *) warn "discord post failed: HTTP $code $(head -c 200 "$TMP/discord.out" 2>/dev/null)";; esac
}

# ── registry ────────────────────────────────────────────────────────────────
# resolve_image repo tag → RES_DIGEST, RES_ARCHES. 0 ok, 4 tag not published, 2 error.
# The digest is sha256 of the exact index bytes, i.e. Docker-Content-Digest.
resolve_image() {
  local repo="$1" tag="$2" tok code
  RES_DIGEST=""; RES_ARCHES=""
  tok=$(curl -s --max-time 30 "https://$REGISTRY/token?scope=repository:$repo:pull&service=$REGISTRY" | jq -r '.token // empty' 2>/dev/null)
  [ -n "$tok" ] || { warn "no GHCR token for $repo"; return 2; }
  printf 'Authorization: Bearer %s\n' "$tok" > "$TMP/ghcr.h"
  code=$(curl -s --max-time 30 -o "$TMP/manifest" -w '%{http_code}' -H @"$TMP/ghcr.h" \
           -H 'Accept: application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json' \
           "https://$REGISTRY/v2/$repo/manifests/$tag")
  case "$code" in 200) ;; 404) return 4 ;; *) warn "GHCR $repo:$tag -> HTTP $code"; return 2 ;; esac
  RES_DIGEST="sha256:$(sha256sum "$TMP/manifest" | cut -d' ' -f1)"
  RES_ARCHES=$(jq -r '[.manifests[]? | select(.platform.os == "linux") | .platform.architecture] | unique | join(" ")' "$TMP/manifest" 2>/dev/null)
  return 0
}
arch_missing() {  # "have arches" → prints missing node arches
  local a out=""
  for a in $NODE_ARCHES; do case " $1 " in *" $a "*) ;; *) out="$out $a" ;; esac; done
  printf '%s' "${out# }"
}

# ── upstream release selection ──────────────────────────────────────────────
JQ_VER='def v: ltrimstr("v") | split("-")[0] | split(".") | map(tonumber? // 0);'
ver_gt() { jq -en --arg a "$1" --arg b "$2" "$JQ_VER (\$a|v) > (\$b|v)" >/dev/null 2>&1; }
is_semver() { [[ "$1" =~ ^v[0-9]+\.[0-9]+\.[0-9]+ ]]; }

RELEASE_SOURCE=""
release_candidates() {  # newest first, one per line
  local code url tag hdr=()
  if [ -n "${GITHUB_TOKEN:-}" ]; then
    printf 'Authorization: Bearer %s\n' "$GITHUB_TOKEN" > "$TMP/gh.h"; hdr=(-H @"$TMP/gh.h")
  fi
  code=$(curl -s --max-time 30 -o "$TMP/releases.json" -w '%{http_code}' "${hdr[@]}" \
           -H 'Accept: application/vnd.github+json' \
           "https://api.github.com/repos/$UPSTREAM_REPO/releases?per_page=50")
  if [ "$code" = 200 ] && jq -e 'type == "array"' "$TMP/releases.json" >/dev/null 2>&1; then
    RELEASE_SOURCE="GitHub releases API"
    jq -r --arg re "$LINE_RE" "$JQ_VER"'
      [ .[] | select((.draft | not) and (.prerelease | not)) | .tag_name | select(test($re)) ]
      | unique | sort_by(v) | reverse | .[]' "$TMP/releases.json"
    return 0
  fi
  # Anonymous API budget is per egress IP and the hub usually exhausts it. The
  # releases/latest web redirect is GitHub's own "newest non-draft,
  # non-prerelease" answer and is not API-rate-limited.
  url=$(curl -s --max-time 30 -o /dev/null -w '%{redirect_url}' "https://github.com/$UPSTREAM_REPO/releases/latest")
  tag="${url##*/tag/}"
  if [ -n "$url" ] && [ "$tag" != "$url" ] && [[ "$tag" =~ $LINE_RE ]]; then
    RELEASE_SOURCE="github.com releases/latest (API HTTP $code)"
    say "$tag"; return 0
  fi
  RELEASE_SOURCE="unavailable (API HTTP $code, web redirect '${url}')"
  return 1
}

# select_target → TGT_TAG TGT_LABEL TGT_SPOKE_DIGEST TGT_HUB_DIGEST TGT_PINNED
# 0 selected, 10 nothing eligible (hold), 2 cannot determine, 3 architecture missing
TGT_NOTES=()
select_target() {
  local cands tag rc pin skipped=0 miss
  TGT_TAG=""; TGT_LABEL=""; TGT_SPOKE_DIGEST=""; TGT_HUB_DIGEST=""; TGT_PINNED=0; TGT_NOTES=()
  pin="${HIVE_UPGRADE_PIN:-$(state_get pin)}"
  if [ -n "$pin" ]; then
    cands=$pin; TGT_PINNED=1; RELEASE_SOURCE="pinned"
  else
    case "$TRACK" in
      release)          release_candidates >"$TMP/cands" || { TGT_NOTES+=("cannot list releases: $RELEASE_SOURCE"); return 2; }
                        cands=$(cat "$TMP/cands") ;;
      stable|candidate) cands=$TRACK; RELEASE_SOURCE="GHCR channel :$TRACK" ;;
      *) TGT_NOTES+=("unknown TRACK=$TRACK"); return 2 ;;
    esac
  fi
  [ -n "$cands" ] || { TGT_NOTES+=("no release matches $LINE_RE"); return 10; }
  for tag in $cands; do
    resolve_image "$SPOKE_REPO" "$tag"; rc=$?
    if [ $rc = 4 ]; then
      TGT_NOTES+=("$tag: $SPOKE_REPO image not published yet, trying older")
      skipped=$((skipped + 1)); [ $skipped -ge 5 ] && break; continue
    fi
    [ $rc = 0 ] || { TGT_NOTES+=("$tag: cannot resolve $SPOKE_REPO"); return 2; }
    local sd=$RES_DIGEST sa=$RES_ARCHES label=$tag
    case "$TRACK" in stable|candidate) [ "$TGT_PINNED" = 1 ] || label="$tag@$(short "$sd")" ;; esac
    if [ "$TGT_PINNED" = 0 ] && is_blocked "$label" "$sd"; then
      TGT_NOTES+=("$label is blocklisted, skipping"); continue
    fi
    miss=$(arch_missing "$sa")
    [ -z "$miss" ] || { TGT_NOTES+=("$REGISTRY/$SPOKE_REPO:$tag has no linux/$miss image (index: ${sa:-none})"); return 3; }
    resolve_image "$HUB_REPO" "$tag"; rc=$?
    if [ $rc = 4 ]; then TGT_NOTES+=("$tag: $HUB_REPO image not published yet, trying older"); skipped=$((skipped + 1)); continue; fi
    [ $rc = 0 ] || { TGT_NOTES+=("$tag: cannot resolve $HUB_REPO"); return 2; }
    miss=$(arch_missing "$RES_ARCHES")
    [ -z "$miss" ] || { TGT_NOTES+=("$REGISTRY/$HUB_REPO:$tag has no linux/$miss image (index: ${RES_ARCHES:-none})"); return 3; }
    TGT_TAG=$tag; TGT_LABEL=$label; TGT_SPOKE_DIGEST=$sd; TGT_HUB_DIGEST=$RES_DIGEST
    return 0
  done
  return 10
}
# The current version is newer than the target: don't downgrade — unless the
# current version is itself blocklisted (e.g. the canary kept a version that
# later failed on reef), or the target is an explicit pin.
is_ahead() {
  [ "$TRACK" = release ] && [ "$TGT_PINNED" = 0 ] && is_semver "$T_VERSION" \
    && ver_gt "$T_VERSION" "$TGT_TAG" && ! is_blocked "$T_VERSION" "$T_DIGEST"
}
target_image() {  # kind
  if [ "$1" = hub ]; then printf '%s/%s:%s@%s' "$REGISTRY" "$HUB_REPO" "$TGT_TAG" "$TGT_HUB_DIGEST"
  else printf '%s/%s:%s@%s' "$REGISTRY" "$SPOKE_REPO" "$TGT_TAG" "$TGT_SPOKE_DIGEST"; fi
}
target_digest() { if [ "$1" = hub ]; then printf '%s' "$TGT_HUB_DIGEST"; else printf '%s' "$TGT_SPOKE_DIGEST"; fi; }

# ── reading a target ────────────────────────────────────────────────────────
# read_target ns deploy container → T_DJ T_IMAGE T_DIGEST T_VERSION T_SEL T_ANN
read_target() {
  local ns="$1" d="$2" c="$3" noat
  T_DJ=$(k -n "$ns" get deploy "$d" -o json 2>"$TMP/err") || { T_ERR=$(head -c 300 "$TMP/err"); return 2; }
  T_IMAGE=$(jq -r --arg c "$c" '.spec.template.spec.containers[] | select(.name == $c) | .image' <<<"$T_DJ")
  [ -n "$T_IMAGE" ] || { T_ERR="container $c not found in $ns/$d"; return 2; }
  T_DIGEST=""; case "$T_IMAGE" in *@sha256:*) T_DIGEST="sha256:${T_IMAGE##*@sha256:}" ;; esac
  T_ANN=$(jq -c '.metadata.annotations // {}' <<<"$T_DJ")
  T_SEL=$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' <<<"$T_DJ")
  T_VERSION=$(jq -r --arg k "$A_VER" '.[$k] // empty' <<<"$T_ANN")
  if [ -z "$T_VERSION" ]; then
    noat=${T_IMAGE%@*}
    case "${noat##*/}" in *:*) T_VERSION=${noat##*:} ;; *) T_VERSION="?" ;; esac
  fi
}
ann() { jq -r --arg k "$1" '.[$k] // empty' <<<"$T_ANN"; }

# ── measuring ───────────────────────────────────────────────────────────────
# measure ns deploy container kind [baseline_restarts]
#   0 healthy · 1 measured UNHEALTHY · 2 COULD NOT MEASURE
# Sets M_MSG, M_POD, M_RESTARTS.
measure() {
  local ns="$1" d="$2" c="$3" kind="$4" base="${5:-}" dj pj info gen obs rep ready sel reason
  M_MSG=""; M_POD=""; M_RESTARTS=""
  dj=$(k -n "$ns" get deploy "$d" -o json 2>"$TMP/err") || { M_MSG="cannot read deployment: $(head -c 200 "$TMP/err")"; return 2; }
  read -r gen obs rep ready <<<"$(jq -r '[.metadata.generation, (.status.observedGeneration // 0), (.spec.replicas // 1), (.status.readyReplicas // 0)] | @tsv' <<<"$dj")"
  if [ "$obs" -lt "$gen" ] || [ "$ready" -lt "$rep" ] || [ "$rep" -lt 1 ]; then
    M_MSG="deployment not ready ($ready/$rep ready, generation $obs/$gen)"; return 1
  fi
  sel=$(jq -r '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")' <<<"$dj")
  pj=$(k -n "$ns" get pods -l "$sel" -o json 2>"$TMP/err") || { M_MSG="cannot list pods: $(head -c 200 "$TMP/err")"; return 2; }
  info=$(jq -r --arg c "$c" '
    [.items[] | select(.metadata.deletionTimestamp == null)] | sort_by(.metadata.creationTimestamp) | last // empty
    | [.metadata.name,
       ((.status.containerStatuses // []) | map(select(.name == $c)) | .[0] // {}) as $s
       | ($s.restartCount // 0), ($s.state.waiting.reason // "-")] | @tsv' <<<"$pj")
  [ -n "$info" ] || { M_MSG="no live pod"; return 1; }
  read -r M_POD M_RESTARTS reason <<<"$info"
  case "$reason" in
    CrashLoopBackOff|ImagePullBackOff|ErrImagePull|CreateContainerConfigError|CreateContainerError|RunContainerError)
      M_MSG="pod $M_POD: $reason"; return 1 ;;
  esac
  if [ -n "$base" ] && [ "$M_RESTARTS" -gt "$base" ]; then
    M_MSG="pod $M_POD restarted ($base -> $M_RESTARTS)"; return 1
  fi
  if [ "$kind" = hub ]; then hub_check "$ns" "$d"; return $?; fi
  spoke_check "$ns" "$M_POD" "$c" "$kind"
}

# GET inside the pod; prints body, then HTTP code on the last line. Empty = exec failed.
pod_get() {  # ns pod container url [cookie]
  local cookie=()
  [ -n "${5:-}" ] && cookie=(-H "Cookie: hive_session=$5")
  k -n "$1" exec "$2" -c "$3" -- curl -s --max-time 30 "${cookie[@]}" -w '\n%{http_code}' "$4" 2>"$TMP/exec.err"
}

JQ_EPOCH='def epoch: capture("^(?<d>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\\.[0-9]+)?(?<z>Z|[+-][0-9]{2}:?[0-9]{2})$")
  | ((.d + "Z") | fromdateiso8601) - (if .z == "Z" then 0 else
      ((.z[1:3] | tonumber) * 3600 + (.z[-2:] | tonumber) * 60) * (if .z[0:1] == "-" then -1 else 1 end) end);'

spoke_check() {  # ns pod container kind
  local ns="$1" pod="$2" c="$3" kind="$4" out code body sessions sid bj pn mk
  out=$(pod_get "$ns" "$pod" "$c" "http://127.0.0.1:$SPOKE_PORT/api/health")
  code=$(tail -n1 <<<"$out")
  [[ "$code" =~ ^[0-9]{3}$ ]] || { M_MSG="cannot exec health probe: $(head -c 200 "$TMP/exec.err")"; return 2; }
  [ "$code" = 200 ] || { M_MSG="/api/health HTTP $code"; return 1; }

  # Fetch the dashboard AS AN OWNER (unauthenticated / is a 401 login page).
  if ! sessions=$(k -n "$ns" exec "$pod" -c "$c" -- cat /data/dashboard-sessions.json 2>"$TMP/exec.err"); then
    [ "$kind" = branded ] && { M_MSG="cannot read sessions: $(head -c 200 "$TMP/exec.err")"; return 2; }
    sessions='{}'
  fi
  sid=$(jq -r --argjson now "$(now_epoch)" "$JQ_EPOCH"'
          to_entries | map(select(.value.Role == "owner") | .exp = ((.value.ExpiresAt | try epoch catch 0) // 0))
          | map(select(.exp > $now)) | sort_by(.exp) | last | .key // empty' <<<"$sessions" 2>/dev/null)

  if [ "$kind" != branded ]; then
    out=$(pod_get "$ns" "$pod" "$c" "http://127.0.0.1:$SPOKE_PORT/" "$sid")
    code=$(tail -n1 <<<"$out")
    [[ "$code" =~ ^[0-9]{3}$ ]] || { M_MSG="cannot exec dashboard fetch: $(head -c 200 "$TMP/exec.err")"; return 2; }
    # Without an owner session the login page (401) is the expected answer.
    if [ "$code" != 200 ] && ! { [ -z "$sid" ] && [ "$code" = 401 ]; }; then M_MSG="dashboard / HTTP $code"; return 1; fi
    grep -qi '<html' <<<"$out" || { M_MSG="dashboard / is not HTML"; return 1; }
    M_MSG="healthy (health 200, dashboard HTTP $code HTML$([ -n "$sid" ] && echo ' as owner'))"; return 0
  fi

  # Branded: the owner's dashboard must carry our product_name and mark.
  [ -n "$sid" ] || { M_MSG="no unexpired owner session to fetch the dashboard with"; return 2; }
  bj=$(k -n "$ns" exec "$pod" -c "$c" -- cat /data/branding/branding.json 2>"$TMP/exec.err") \
    || { M_MSG="cannot read branding.json: $(head -c 200 "$TMP/exec.err")"; return 2; }
  pn=$(jq -r '.product_name // empty' <<<"$bj" 2>/dev/null); mk=$(jq -r '.mark // empty' <<<"$bj" 2>/dev/null)
  # Empty marks would make grep -F match anything and certify a stock page.
  [ -n "$pn" ] && [ -n "$mk" ] || { M_MSG="branding.json has no product_name/mark"; return 2; }
  out=$(pod_get "$ns" "$pod" "$c" "http://127.0.0.1:$SPOKE_PORT/" "$sid")
  code=$(tail -n1 <<<"$out")
  [[ "$code" =~ ^[0-9]{3}$ ]] || { M_MSG="cannot exec dashboard fetch: $(head -c 200 "$TMP/exec.err")"; return 2; }
  [ "$code" = 200 ] || { M_MSG="owner dashboard HTTP $code"; return 1; }
  body=${out%$'\n'*}
  grep -qF -- "$pn" <<<"$body" || { M_MSG="branding FAIL: product_name '$pn' missing from served dashboard (${#body} bytes)"; return 1; }
  grep -qF -- "$mk" <<<"$body" || { M_MSG="branding FAIL: mark '$mk' missing from served dashboard (${#body} bytes)"; return 1; }
  M_MSG="healthy + branded ($pn $mk in served dashboard)"; return 0
}

hub_check() {  # ns deploy — HTTP 200 + HTML through the Service (apiserver service proxy)
  local ns="$1" d="$2" out
  if out=$(k get --raw "/api/v1/namespaces/$ns/services/$d:$HUB_SERVICE_PORT/proxy/" 2>"$TMP/err"); then
    grep -qi '<html' <<<"$out" && grep -qF -- "$HUB_MARK" <<<"$out" \
      || { M_MSG="hub service answered but not with the hub page"; return 1; }
    M_MSG="healthy (service 200, hub page served)"; return 0
  fi
  if grep -Eqi 'forbidden|unauthorized|unable to connect to the server|certificate|credentials' "$TMP/err"; then
    M_MSG="cannot query hub service: $(head -c 200 "$TMP/err")"; return 2
  fi
  M_MSG="hub service error: $(head -c 200 "$TMP/err")"; return 1
}

# verify: retry until healthy; returns the last result.
verify() {  # ns d c kind [baseline]
  local i rc=2
  for ((i = 1; i <= VERIFY_ATTEMPTS; i++)); do
    measure "$@"; rc=$?
    [ $rc = 0 ] && return 0
    say "    check $i/$VERIFY_ATTEMPTS: $([ $rc = 1 ] && echo UNHEALTHY || echo UNKNOWN) — $M_MSG"
    [ $i -lt "$VERIFY_ATTEMPTS" ] && sleep "$VERIFY_INTERVAL"
  done
  return $rc
}

# soak: watch for SOAK_SECONDS; two consecutive measured failures fail it.
soak() {  # ns d c kind baseline
  local end left fails=0 rc base="$5"
  end=$(( $(now_epoch) + SOAK_SECONDS ))
  say "    soaking ${SOAK_SECONDS}s"
  while :; do
    left=$(( end - $(now_epoch) )); [ $left -gt 0 ] || break
    sleep $(( left < SOAK_INTERVAL ? left : (SOAK_INTERVAL > 0 ? SOAK_INTERVAL : 1) ))
    measure "$1" "$2" "$3" "$4" "$base"; rc=$?
    case $rc in
      0) fails=0 ;;
      1) fails=$((fails + 1)); say "    soak: UNHEALTHY ($fails) — $M_MSG"; [ $fails -ge 2 ] && return 1 ;;
      *) say "    soak: UNKNOWN — $M_MSG" ;;
    esac
  done
  verify "$1" "$2" "$3" "$4" "$base"
}

wait_rollout() {  # ns d
  timeout $((ROLLOUT_TIMEOUT + 30)) kubectl -n "$1" rollout status "deploy/$2" --timeout="${ROLLOUT_TIMEOUT}s" >"$TMP/rollout" 2>&1 \
    || say "    rollout status: $(tail -c 200 "$TMP/rollout")"
}

# ── mutation ────────────────────────────────────────────────────────────────
# One strategic-merge patch sets the image AND records the rollback target, so
# the change and its way back land atomically.
patch_json() {  # container image annotations-json(null deletes)
  jq -cn --arg c "$1" --arg img "$2" --argjson a "$3" \
    '{metadata: {annotations: $a}, spec: {template: {spec: {containers: [{name: $c, image: $img}]}}}}'
}

rollback() {  # ns d c kind prev_image bad_image reason ; uses OLD_* captured before the upgrade
  local ns="$1" d="$2" c="$3" kind="$4" prev="$5" bad="$6" reason="$7" a
  say "  !! ROLLBACK $ns -> $prev ($reason)"
  a=$(jq -cn --arg p "$A_PREV" --arg pv "$OLD_PREV" --arg vk "$A_VER" --arg v "$OLD_VER" \
              --arg ak "$A_AT" --arg at "$OLD_AT" --arg pk "$A_PVER" --arg ppv "$OLD_PVER" \
              --arg rk "$A_RBF" --arg bad "$bad" --arg tk "$A_RBAT" --arg now "$(now_iso)" '
        {($p): (if $pv == "" then null else $pv end), ($vk): (if $v == "" then null else $v end),
         ($ak): (if $at == "" then null else $at end), ($pk): (if $ppv == "" then null else $ppv end),
         ($rk): $bad, ($tk): $now}')
  km -n "$ns" patch deploy "$d" --type strategic -p "$(patch_json "$c" "$prev" "$a")" >"$TMP/err" 2>&1 \
    || { ROLLBACK_BROKEN="rollback patch failed: $(head -c 200 "$TMP/err")"; return 1; }
  wait_rollout "$ns" "$d"
  if verify "$ns" "$d" "$c" "$kind"; then say "    rolled back and healthy: $M_MSG"; return 0; fi
  ROLLBACK_BROKEN="after rollback: $M_MSG"; return 1
}

label_of() {  # idx ns
  if [ "$1" = 0 ]; then printf 'canary %s' "$2"; else
    case "$2" in hive) printf hive ;; *) printf '%s' "${2#hive-}" ;; esac
  fi
}

# ── status ──────────────────────────────────────────────────────────────────
cmd_status() {
  local rc t ns d c kind td state dig
  state_load || STATE_JSON='{"data":{}}'
  NODE_ARCHES=$(k get nodes -o json 2>/dev/null | jq -r '[.items[].status.nodeInfo.architecture] | unique | join(" ")')
  say "hive-upgrade status  $(now_iso)"
  say "  track: $TRACK  line: $LINE_RE  nodes: ${NODE_ARCHES:-UNREADABLE}"
  select_target; rc=$?
  case $rc in
    0)  say "  target: $TGT_LABEL  (source: $RELEASE_SOURCE)"
        say "    spoke $(target_image spoke)"
        say "    hub   $(target_image hub)" ;;
    10) say "  target: none eligible (source: ${RELEASE_SOURCE:-?})" ;;
    3)  say "  target: BLOCKED — architecture missing" ;;
    *)  say "  target: UNKNOWN (cannot determine; source: ${RELEASE_SOURCE:-?})" ;;
  esac
  for t in "${TGT_NOTES[@]}"; do say "    note: $t"; done
  say ""
  printf '  %-13s %-10s %-14s %-10s %-22s %s\n' TARGET VERSION DIGEST STATE UPGRADED-AT PREVIOUS-IMAGE
  for t in $TARGETS; do
    IFS='|' read -r ns d c kind <<<"$t"
    if ! read_target "$ns" "$d" "$c"; then printf '  %-13s UNREADABLE: %s\n' "$ns" "$T_ERR"; continue; fi
    td=$(target_digest "$kind"); dig=${T_DIGEST:-none}
    if [ $rc != 0 ]; then state="?"
    elif [ "$T_DIGEST" = "$td" ]; then state=current
    elif is_ahead; then state=ahead
    else state=behind; fi
    printf '  %-13s %-10s %-14s %-10s %-22s %s\n' "$ns" "$T_VERSION" "$(short "$dig")" "$state" "$(or "$(ann "$A_AT")" "-")" "$(or "$(ann "$A_PREV")" "-")"
  done
  say ""
  say "  contributors ($CONTRIB_NS, report only — not managed):"
  if k -n "$CONTRIB_NS" get deploy -o json >"$TMP/contrib" 2>/dev/null; then
    jq -r '.items[] | "    \(.metadata.name): \([.spec.template.spec.containers[].image] | unique | join(", ")) ready=\(.status.readyReplicas // 0)/\(.spec.replicas // 1)"' "$TMP/contrib"
    if [ $rc = 0 ]; then
      resolve_image "$CONTRIB_REPO" "$TGT_TAG" >/dev/null 2>&1 \
        && say "    $REGISTRY/$CONTRIB_REPO:$TGT_TAG available ($(short "$RES_DIGEST"), ${RES_ARCHES})" \
        || say "    $REGISTRY/$CONTRIB_REPO:$TGT_TAG not resolvable"
    fi
  else say "    (unreadable)"; fi
  say ""
  say "  blocklist: $(or "$(state_get blocklist | paste -sd' ' -)" "(empty)")"
  say "  pin: $(or "$(state_get pin)" "(none)")"
  say "  last attempt: $(or "$(state_get last_attempt)" "-") at $(or "$(state_get last_attempt_at)" "-")"
  say "  last result: $(or "$(state_get last_result)" "-")"
  say "  last success: $(or "$(state_get last_success)" "-")   last rollback: $(or "$(state_get last_rollback_at)" "-")"
  [ -n "$(state_get running_since)" ] && say "  RUNNING since $(state_get running_since)"
  return 0
}

# ── run ─────────────────────────────────────────────────────────────────────
finish() {  # rc result [discord-message]
  local rc="$1" res="$2"
  say ""; say "RESULT: $res"
  state_set last_result "$res" last_run_at "$(now_iso)" running_since "" history "$(history_add "$res")" >/dev/null || warn "could not record result in state"
  LOCKED=0
  [ -n "${3:-}" ] && discord "$3"
  exit "$rc"
}

cmd_run() {
  local rc t ns d c kind idx=0 n from="" done_list=() changed=0 td timg prev ann_patch
  n=$(wc -w <<<"$TARGETS")
  say "hive-upgrade run  $(now_iso)  track=$TRACK$([ "$DRY" = 1 ] && echo '  DRY RUN')"
  state_load || { say "ABORT: cannot read state (blocklist unknown) — refusing to run"; exit 2; }

  NODE_ARCHES=$(k get nodes -o json 2>"$TMP/err" | jq -r '[.items[].status.nodeInfo.architecture] | unique | join(" ")')
  [ -n "$NODE_ARCHES" ] || finish 2 "abort: cannot read node architecture ($(head -c 150 "$TMP/err"))"

  if [ "$FORCE" != 1 ]; then
    local lr rs; lr=$(state_get last_rollback_at_epoch); rs=$(state_get running_since_epoch)
    if [ -n "$lr" ] && [ $(( $(now_epoch) - lr )) -lt $(( COOLDOWN_HOURS * 3600 )) ]; then
      say "holding: cooldown — last rollback $(state_get last_rollback_at) (< ${COOLDOWN_HOURS}h ago); FORCE=1 to override"
      [ "$DRY" = 1 ] || exit 0
    fi
    if [ -n "$(state_get running_since)" ] && [ -n "$rs" ] && [ $(( $(now_epoch) - rs )) -lt "$LOCK_TTL_SECONDS" ]; then
      say "ABORT: another run holds the lock since $(state_get running_since); FORCE=1 to override"
      exit 2
    fi
  fi

  select_target; rc=$?
  for t in "${TGT_NOTES[@]}"; do say "  note: $t"; done
  case $rc in
    0) ;;
    10) finish 0 "hold: no eligible version (source: ${RELEASE_SOURCE:-?})" ;;
    3) finish 2 "abort: architecture missing — ${TGT_NOTES[-1]}" ;;
    *) finish 2 "abort: cannot determine target version (${RELEASE_SOURCE:-?})" ;;
  esac
  say "target $TGT_LABEL  (source: $RELEASE_SOURCE, nodes: $NODE_ARCHES)"
  say "  spoke $(target_image spoke)"
  say "  hub   $(target_image hub)"

  # Plan first: is anything to do at all?
  local todo=0
  for t in $TARGETS; do
    IFS='|' read -r ns d c kind <<<"$t"
    read_target "$ns" "$d" "$c" || finish 2 "abort: cannot read $ns/$d before starting ($T_ERR)"
    [ "$T_DIGEST" = "$(target_digest "$kind")" ] && continue
    if is_ahead; then continue; fi
    todo=$((todo + 1))
  done
  if [ $todo = 0 ]; then
    say "all targets already at $TGT_LABEL (or ahead) — nothing to do"
    finish 0 "noop: fleet at $TGT_LABEL"
  fi

  if [ "$DRY" != 1 ]; then
    state_set running_since "$(now_iso)" running_since_epoch "$(now_epoch)" \
              last_attempt "$TGT_LABEL" last_attempt_at "$(now_iso)" >/dev/null \
      || { say "ABORT: could not take the run lock in $STATE_NS/$STATE_CM"; exit 2; }
    LOCKED=1
  fi

  for t in $TARGETS; do
    IFS='|' read -r ns d c kind <<<"$t"
    local label; label=$(label_of $idx "$ns"); idx=$((idx + 1))
    say ""; say "[$idx/$n] $label ($ns/$d)"
    read_target "$ns" "$d" "$c" || { up_abort "$label" "cannot read deployment: $T_ERR"; }
    td=$(target_digest "$kind"); timg=$(target_image "$kind")
    if [ "$T_DIGEST" = "$td" ]; then say "  already at $TGT_LABEL"; done_list+=("$label ✓"); continue; fi
    if is_ahead; then
      say "  at $T_VERSION, ahead of $TGT_TAG — not downgrading"; done_list+=("$label ✓"); continue
    fi
    [ -z "$from" ] && from=$T_VERSION

    # Preflight: judge the CURRENT image first. If we can't prove it is healthy
    # now, a post-upgrade failure would prove nothing either.
    measure "$ns" "$d" "$c" "$kind"; rc=$?
    say "  preflight on $T_VERSION: $([ $rc = 0 ] && echo OK || { [ $rc = 1 ] && echo UNHEALTHY || echo UNKNOWN; }) — $M_MSG"
    [ $rc = 0 ] || up_abort "$label" "preflight on current $T_VERSION not healthy ($M_MSG); left untouched"

    # Rollback target: the digest-pinned spec image, else the digest the pod actually runs.
    if [ -n "$T_DIGEST" ]; then prev=$T_IMAGE
    else
      prev=$(k -n "$ns" get pods -l "$T_SEL" -o json 2>/dev/null | jq -r --arg c "$c" \
        '[.items[] | select(.metadata.deletionTimestamp == null) | .status.containerStatuses[]? | select(.name == $c) | .imageID] | .[0] // empty' \
        | sed 's#^docker-pullable://##')
      case "$prev" in *@sha256:*) ;; *) up_abort "$label" "cannot resolve a rollback digest for $T_IMAGE; left untouched" ;; esac
    fi
    OLD_PREV=$(ann "$A_PREV"); OLD_VER=$(ann "$A_VER"); OLD_AT=$(ann "$A_AT"); OLD_PVER=$(ann "$A_PVER")
    say "  $T_VERSION -> $TGT_LABEL"
    say "    image     $timg"
    say "    rollback  $prev"
    ann_patch=$(jq -cn --arg p "$A_PREV" --arg prev "$prev" --arg pk "$A_PVER" --arg pv "$T_VERSION" \
                       --arg vk "$A_VER" --arg v "$TGT_LABEL" --arg ak "$A_AT" --arg at "$(now_iso)" \
                       --arg rk "$A_RBF" --arg tk "$A_RBAT" \
                '{($p): $prev, ($pk): $pv, ($vk): $v, ($ak): $at, ($rk): null, ($tk): null}')
    if [ "$DRY" = 1 ]; then
      km -n "$ns" patch deploy "$d" --type strategic -p "$(patch_json "$c" "$timg" "$ann_patch")"
      done_list+=("$label (planned)"); continue
    fi
    if ! km -n "$ns" patch deploy "$d" --type strategic -p "$(patch_json "$c" "$timg" "$ann_patch")" >"$TMP/err" 2>&1; then
      up_abort "$label" "patch failed: $(head -c 200 "$TMP/err")"
    fi
    changed=$((changed + 1))
    wait_rollout "$ns" "$d"
    verify "$ns" "$d" "$c" "$kind"; rc=$?
    [ $rc = 0 ] && { say "  verified: $M_MSG"; local base=$M_RESTARTS
      if [ "$idx" -lt "$n" ]; then
        soak "$ns" "$d" "$c" "$kind" "$base"; rc=$?
        [ $rc = 0 ] && say "  soak passed: $M_MSG"
      fi; }
    case $rc in
      0) done_list+=("$label ✓") ;;
      1) up_rollback "$ns" "$d" "$c" "$kind" "$prev" "$timg" "$label" "$M_MSG" ;;
      *) up_abort "$label" "could not verify after upgrade ($M_MSG). NOT rolled back — unmeasured is not unhealthy. $ns is on $TGT_LABEL; rollback target: $prev" ;;
    esac
  done

  if [ "$DRY" = 1 ]; then
    discord "Hive upgraded ${from:-?} → $TGT_LABEL ($(printf '%s, ' "${done_list[@]}" | sed 's/, $//'))"
    finish 0 "dry-run: would upgrade to $TGT_LABEL"
  fi
  local msg
  msg="Hive upgraded ${from:-?} → $TGT_LABEL ($(printf '%s, ' "${done_list[@]}" | sed 's/, $//'))"
  state_set last_success "$TGT_LABEL" last_success_at "$(now_iso)" >/dev/null || true
  if [ $changed -gt 0 ]; then finish 0 "success: $msg" "$msg"; else finish 0 "success: $msg"; fi
}

progress() { [ ${#done_list[@]} -gt 0 ] && printf ' Done: %s.' "$(printf '%s, ' "${done_list[@]}" | sed 's/, $//')"; }

up_abort() {  # label reason
  local msg
  msg="🚨 Hive upgrade ${from:-?} → $TGT_LABEL ABORTED at $1: $2.$(progress) Remaining targets untouched."
  if [ "$MUTATED" = 1 ]; then finish 2 "abort at $1: $2" "$msg"; else finish 2 "abort at $1 (nothing changed): $2"; fi
}

up_rollback() {  # ns d c kind prev bad label reason
  local ns="$1" label="$7" reason="$8" bl res msg
  bl=$(printf '%s\n%s' "$(state_get blocklist)" "$TGT_LABEL" | sed '/^$/d' | sort -u)
  state_set blocklist "$bl" last_rollback_at "$(now_iso)" last_rollback_at_epoch "$(now_epoch)" >/dev/null \
    || warn "could not write blocklist"
  ROLLBACK_BROKEN=""
  if rollback "$ns" "$2" "$3" "$4" "$5" "$6" "$reason"; then
    res="rolled back $label from $TGT_LABEL: $reason; $TGT_LABEL blocklisted"
    msg="🚨 Hive upgrade ${from:-?} → $TGT_LABEL FAILED on $label: $reason. Rolled back $label to $(short "${5##*@}") and blocklisted $TGT_LABEL.$(progress) Stopped; later targets untouched."
    finish 1 "$res" "$msg"
  fi
  res="ROLLBACK OF $label DID NOT RECOVER ($ROLLBACK_BROKEN) after: $reason"
  msg="🚨🚨 Hive upgrade to $TGT_LABEL failed on $label ($reason) AND the rollback to $5 did not recover: $ROLLBACK_BROKEN. Manual action needed: kubectl -n $ns get pods; kubectl -n $ns rollout status deploy/$2"
  finish 2 "$res" "$msg"
}

cmd_state_edit() {  # block|unblock|pin|unpin [version]
  local v="${2:-}" bl
  state_load || { say "cannot read state"; exit 2; }
  case "$1" in
    block)   [ -n "$v" ] || { say "usage: $0 block VERSION"; exit 2; }
             bl=$(printf '%s\n%s' "$(state_get blocklist)" "$v" | sed '/^$/d' | sort -u); state_set blocklist "$bl" ;;
    unblock) [ -n "$v" ] || { say "usage: $0 unblock VERSION"; exit 2; }
             bl=$(state_get blocklist | grep -Fxv -e "$v"); state_set blocklist "$bl" ;;
    pin)     [ -n "$v" ] || { say "usage: $0 pin VERSION"; exit 2; }; state_set pin "$v" ;;
    unpin)   state_set pin "" ;;
  esac >/dev/null || exit 2
  say "blocklist: $(or "$(state_get blocklist | paste -sd' ' -)" "(empty)")   pin: $(or "$(state_get pin)" "(none)")"
}

case "${1:-status}" in
  status) cmd_status ;;
  run)    cmd_run ;;
  block|unblock|pin|unpin) cmd_state_edit "$@" ;;
  *) say "usage: $0 status|run|block VERSION|unblock VERSION|pin VERSION|unpin"; exit 2 ;;
esac
