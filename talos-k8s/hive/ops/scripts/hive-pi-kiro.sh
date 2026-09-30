#!/usr/bin/env bash
# hive-pi-kiro.sh — keep the Kiro provider for `pi` installed in every hive.
#
# WHY
# ---
# The owner's Kiro Power subscription is reached through the `pi` backend (v5
# has no kiro backend) plus the pi package pi-kiro-api, which registers the
# provider id `kiro-api-key` (models `kiro-api-key/<model>`). Two things make a
# plain `pi install npm:pi-kiro-api` unusable here:
#
#   1. PERSISTENCE. `pi install npm:…` writes to the image's global npm prefix
#      (/usr/local, the container overlay). It is gone after every pod restart,
#      and a `pi` agent whose provider is missing dies at launch.
#   2. CORRECTNESS. pi-kiro-api 0.3.0 does not work with the pi in the image:
#        - it registers apiKey "$KIRO_API_KEY", which pi 0.73 sends literally
#          (403 "bearer token invalid"); the fork branch below fixes that for
#          0.73 but pi 0.87 inverted the rule (it resolves "$VAR" templates and
#          sends a bare name literally), so the stream now reads KIRO_API_KEY
#          from the environment first;
#        - pi 0.8x moved the system prompt and the tool set into
#          role:"system" messages, which the extension turned into a toolResult
#          with no toolUseId (400 "Invalid tool use format.").
#      The fix for both is pi-kiro-api-pi087.patch, applied on top of the
#      pinned fork commit.
#
# So the package is a git checkout on each hive's PVC, /data/pi-packages/
# pi-kiro-api, pinned to PIN_SHA plus the vendored patch, and every agent's own
# ~/.pi/agent/settings.json (per-agent HOME /data/home/agents/<agent>, also on
# the PVC) lists it as a LOCAL-PATH package. Both survive pod restarts; nothing
# is written to the image. A new agent needs this run once (the hive-shared-auth
# CronJob runs `reconcile` every 30 min) before it is placed on a kiro rung.
#
# SWITCHING BACK TO UPSTREAM: once satiyap/pi-kiro-api releases both fixes
# (PR satiyap/pi-kiro-api#1 covers only the apiKey half, and only for pi 0.73),
# set HIVE_PI_KIRO_REPO to the upstream repo and HIVE_PI_KIRO_SHA to the
# release commit, set HIVE_PI_KIRO_PATCH="" and run `reconcile`.
#
# The key itself is NOT handled here: KIRO_API_KEY reaches agents from the hive
# container env (Secret kiro-api), inherited by the tmux server.
#
# USAGE
#   hive-pi-kiro.sh check       # report pin + per-agent registration, change nothing
#   hive-pi-kiro.sh reconcile   # install/repin the checkout, register every agent

# shellcheck source=hive-lib.sh
. "${HIVE_LIB:-$(dirname "$0")/hive-lib.sh}"
hive_kube_env

set -u

NAMESPACES="${HIVE_PI_KIRO_NAMESPACES:-hive hive-reef hive-hanthor}"
REPO="${HIVE_PI_KIRO_REPO:-https://github.com/hanthor/pi-kiro-api.git}"
PIN_SHA="${HIVE_PI_KIRO_SHA:-1c0611592852279f1bcd8c491a9ea410ecee0cb3}"   # fix-apikey-env-reference
PATCH_FILE="${HIVE_PI_KIRO_PATCH-$(dirname "$0")/pi-kiro-api-pi087.patch}"
PKG_DIR=/data/pi-packages/pi-kiro-api
ACTION="${1:-check}"
case "$ACTION" in check|reconcile) ;; *) echo "usage: $0 check|reconcile" >&2; exit 2 ;; esac

patch_sum=none
if [ -n "$PATCH_FILE" ]; then
  [ -s "$PATCH_FILE" ] || { echo "ERROR: patch $PATCH_FILE missing" >&2; exit 1; }
  patch_sum=$(sha256sum "$PATCH_FILE" | cut -c1-16)
fi
WANT_PIN="$PIN_SHA+$patch_sum"

# In-pod half. stdin = the patch (possibly empty). Prints one line per agent.
# shellcheck disable=SC2016
INPOD='
set -u
act=$1 repo=$2 sha=$3 want=$4 d=$5
p=$(mktemp); cat > "$p"
G="git -c safe.directory=* -C $d"
have=$(cat "$d/.hive-pin" 2>/dev/null || echo none)
if [ "$have" != "$want" ]; then
  if [ "$act" = check ]; then echo "PIN  $have (want $want)"
  else
    mkdir -p "$(dirname "$d")"
    [ -d "$d/.git" ] || git clone -q "$repo" "$d" || { echo "PIN  clone failed"; exit 1; }
    $G remote set-url origin "$repo"
    $G cat-file -e "$sha^{commit}" 2>/dev/null || $G fetch -q origin || { echo "PIN  fetch failed"; exit 1; }
    $G -c advice.detachedHead=false checkout -q -f "$sha" && $G clean -qfdx \
      || { echo "PIN  checkout failed"; exit 1; }
    if [ -s "$p" ]; then $G apply "$p" || { echo "PIN  patch failed"; exit 1; }; fi
    echo "$want" > "$d/.hive-pin"
    chown -R dev:node "$(dirname "$d")"; chmod -R u=rwX,g=rX,o=rX "$(dirname "$d")"
    echo "PIN  $have -> $want"
  fi
else echo "PIN  ok $want"; fi
rm -f "$p"
for u in $(getent passwd | awk -F: "/^hive-/{print \$1}"); do
  a=${u#hive-}; h=/data/home/agents/$a
  [ -d "$h" ] || { echo "AGENT $a no-home"; continue; }
  s=$h/.pi/agent/settings.json
  if [ -f "$s" ] && grep -q "pi-packages/pi-kiro-api" "$s"; then echo "AGENT $a ok"; continue; fi
  if [ "$act" = check ]; then echo "AGENT $a missing"; continue; fi
  if su-exec "$u" env HOME="$h" timeout 60 pi install "$d" >/dev/null 2>&1; then echo "AGENT $a registered"
  else echo "AGENT $a register-failed"; fi
done
'

rc=0
for ns in $NAMESPACES; do
  pod=$(hive_pod "$ns")
  [ -n "$pod" ] || { printf '%-13s no running hive pod — skipped\n' "$ns"; rc=1; continue; }
  out=$( { [ -n "$PATCH_FILE" ] && cat "$PATCH_FILE"; } | timeout 240 kubectl exec -i -n "$ns" "$pod" -c hive -- \
           sh -c "$INPOD" sh "$ACTION" "$REPO" "$PIN_SHA" "$WANT_PIN" "$PKG_DIR" 2>&1) || rc=1
  printf '%s\n' "$out" | sed "s/^/$(printf '%-13s' "$ns") /"
  printf '%s' "$out" | grep -qE 'failed|missing|no-home|\(want ' && rc=1
done
exit $rc
