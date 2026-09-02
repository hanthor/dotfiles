#!/usr/bin/env bash
# contribute-k8s-fleet.sh — register a Hive backend against BOTH hubs and
# deploy it as a persistent cluster contributor (claude | agy | pi | kiro).
#
# WHY THIS EXISTS: upstream `just contribute-k8s` only emits a HEADLESS pod and
# supports claude/litellm/copilot/goose. agy/pi/kiro (and codex creds) are
# refused there. This deploys the INTERACTIVE relay in a tmux PTY — the same
# path `just contribute-hive` uses locally — which every backend supports, plus
# a self-heal watchdog sidecar. See talos-k8s/hive-contributors/README.md.
#
# WHAT IT DOES, per backend:
#   1. Ensures a multi-hub registration exists (delegates to the upstream
#      `just contribute-move <backend>` in a hive v4 checkout, which reissues a
#      token per hub and writes ~/.config/hive/contributor.env). Registration
#      is the only interactive step (GitHub auth); it CANNOT run in a pod.
#   2. Reads contributor.env + gh-auth.env and creates the k8s Secret
#      hive-contrib-<name> (HIVE_HUB, HIVE_REGISTRATION_TOKEN, GH_TOKEN) plus
#      the backend's own credential.
#   3. Applies the matching Deployment manifest.
#
# It NEVER writes secrets to the repo and NEVER runs kubectl without an explicit
# --apply. Default is dry-run: it prints what it would do.
set -euo pipefail

# ── Config ──
NS=hive-contributors
HIVE_CHECKOUT="${HIVE_CHECKOUT:-/tmp/hive-v4}"
MANIFEST_DIR="$(cd "$(dirname "$0")" && pwd)"
CONF="${HOME}/.config/hive/contributor.env"
GH_AUTH="${HOME}/.config/hive/gh-auth.env"
# Both hubs, in a fixed order (token order must match).
HUBS_DEFAULT="wss://hive.tunaos.org/contribute,wss://hosted-kubestellar-hive-ojv6.hive.kubestellar.io/contribute"

usage() {
  cat >&2 <<EOF
usage: $0 <backend> [--apply]

  backend   claude | agy | pi | kiro
  --apply   actually create the Secret + apply the Deployment (default: dry-run)

env:
  HIVE_HUB        override the two-hub list (default: tunaos + hosted-kubestellar)
  HIVE_CHECKOUT   path to a 'git clone -b v4 kubestellar/hive' (default: /tmp/hive-v4)
  KUBECONFIG      must select the cluster (tailscale context recommended)

Secret credential per backend (must be in your shell env when applying):
  claude  ANTHROPIC_API_KEY   (or seed ~/.claude OAuth on the PVC afterwards)
  agy     (none — seed ~/.gemini OAuth on the PVC afterwards)
  pi      OPENAI_API_KEY
  kiro    KIRO_API_KEY
EOF
  exit 2
}

BACKEND="${1:-}"; [ -n "$BACKEND" ] || usage
APPLY=0; [ "${2:-}" = "--apply" ] && APPLY=1

# Map the requested backend to (AGENT_BACKEND value, secret name, manifest).
# All four backends here authenticate via OAuth/session state SEEDED ONTO THE
# PVC (see README first-run auth), so no API key is required in the Secret:
#   claude  ~/.claude            (or set ANTHROPIC_API_KEY to override)
#   agy     ~/.antigravity, ~/.gemini
#   pi      ~/.pi/agent          (openai-codex ChatGPT OAuth)
#   kiro    ~/.local/share/kiro-cli, ~/.kiro
# CREDKEYS lists any OPTIONAL env-var overrides picked up from the shell.
case "$BACKEND" in
  claude) SECRET=hive-contrib-claude;   MANIFEST=claude.yaml;   CREDKEYS="ANTHROPIC_API_KEY"; SEED="~/.claude" ;;
  agy)    SECRET=hive-contrib-agy;      MANIFEST=agy.yaml;      CREDKEYS=""; SEED="~/.antigravity ~/.gemini" ;;
  pi)     SECRET=hive-contrib-pi-codex; MANIFEST=pi-codex.yaml; CREDKEYS="OPENAI_API_KEY"; SEED="~/.pi/agent" ;;
  kiro)   SECRET=hive-contrib-kiro;     MANIFEST=kiro.yaml;     CREDKEYS="KIRO_API_KEY"; SEED="~/.local/share/kiro-cli ~/.kiro" ;;
  *) echo "ERROR: unknown backend '$BACKEND'" >&2; usage ;;
esac

export HIVE_HUB="${HIVE_HUB:-$HUBS_DEFAULT}"

echo "=== contribute-k8s-fleet: $BACKEND ==="
echo "  hubs:     $HIVE_HUB"
echo "  secret:   $SECRET"
echo "  manifest: $MANIFEST_DIR/$MANIFEST"
echo "  mode:     $([ "$APPLY" = 1 ] && echo APPLY || echo dry-run)"
echo

# ── Step 1: ensure multi-hub registration ──
# `just contribute-move` is the upstream recipe that reissues a token per hub
# and writes contributor.env. It is interactive (GitHub auth). We do NOT
# reimplement it; we require the checkout and run it.
if [ ! -d "$HIVE_CHECKOUT" ]; then
  echo "ERROR: no hive checkout at $HIVE_CHECKOUT." >&2
  echo "  git clone -b v4 https://github.com/kubestellar/hive $HIVE_CHECKOUT" >&2
  exit 1
fi

# Does contributor.env already cover BOTH hubs for THIS backend?
need_register=1
if [ -f "$CONF" ]; then
  cur_hubs=$(grep -m1 '^HIVE_HUB=' "$CONF" | cut -d= -f2- || true)
  cur_backend=$(grep -m1 '^AGENT_BACKEND=' "$CONF" | cut -d= -f2- || true)
  if [ "$cur_hubs" = "$HIVE_HUB" ] && [ "$cur_backend" = "$BACKEND" ]; then
    need_register=0
    echo "contributor.env already registered $BACKEND on both hubs — reusing it."
  fi
fi

if [ "$need_register" = 1 ]; then
  echo "Registering $BACKEND on both hubs via 'just contribute-move' (interactive)..."
  if [ "$APPLY" != 1 ]; then
    echo "  [dry-run] would run: (cd $HIVE_CHECKOUT && HIVE_HUB=$HIVE_HUB just contribute-move $BACKEND)"
  else
    ( cd "$HIVE_CHECKOUT" && HIVE_HUB="$HIVE_HUB" just contribute-move "$BACKEND" )
  fi
fi

# ── Step 2: build the Secret from contributor.env + gh-auth.env ──
read_conf() { grep -m1 "^$1=" "$CONF" 2>/dev/null | cut -d= -f2- || true; }

TOKENS=""; HUBS=""; GH=""
if [ -f "$CONF" ]; then TOKENS=$(read_conf HIVE_REGISTRATION_TOKEN); HUBS=$(read_conf HIVE_HUB); fi
[ -f "$GH_AUTH" ] && GH=$(grep -m1 '^GH_TOKEN=' "$GH_AUTH" | cut -d= -f2- || true)
[ -z "$GH" ] && GH=$(gh auth token 2>/dev/null || true)

# Collect the backend credential from the shell env.
declare -a CRED_ARGS=()
for k in $CREDKEYS; do
  v="${!k:-}"
  if [ -z "$v" ]; then
    echo "note: \$$k not set — $BACKEND will use OAuth/session state seeded on the PVC." >&2
    echo "      after first apply, seed it once:  $SEED  (see README first-run auth)" >&2
  else
    CRED_ARGS+=( "--from-literal=$k=$v" )
  fi
done

if [ "$APPLY" != 1 ]; then
  echo
  # NEVER print secret VALUES — only whether each is present.
  present() { [ -n "$1" ] && echo set || echo MISSING; }
  echo "[dry-run] would create secret/$SECRET in ns/$NS with keys:"
  echo "    HIVE_HUB=${HUBS:-<from registration>}"
  echo "    HIVE_REGISTRATION_TOKEN=<$(present "$TOKENS")>"
  echo "    GH_TOKEN=<$(present "$GH")>"
  for k in $CREDKEYS; do printf '    %s=<%s>\n' "$k" "$([ -n "${!k:-}" ] && echo set || echo unset)"; done
  echo "[dry-run] would apply: $MANIFEST_DIR/$MANIFEST"
  echo
  echo "Re-run with --apply to perform these actions."
  exit 0
fi

# Hard checks before mutating the cluster.
[ -n "$TOKENS" ] || { echo "ERROR: no HIVE_REGISTRATION_TOKEN in $CONF — registration did not complete." >&2; exit 1; }
[ -n "$HUBS" ]   || { echo "ERROR: no HIVE_HUB in $CONF." >&2; exit 1; }
[ -n "$GH" ]     || { echo "ERROR: no GH_TOKEN (gh-auth.env or 'gh auth token')." >&2; exit 1; }

echo "Ensuring namespace, watchdog ConfigMap, and image-pull secret..."
kubectl apply -f "$MANIFEST_DIR/namespace.yaml"
kubectl apply -f "$MANIFEST_DIR/watchdog-configmap.yaml"
if ! kubectl -n "$NS" get secret ghcr-auth >/dev/null 2>&1; then
  echo "  creating ghcr-auth image-pull secret from gh token"
  kubectl create secret docker-registry ghcr-auth -n "$NS" \
    --docker-server=ghcr.io \
    --docker-username="$(gh api user -q .login)" \
    --docker-password="$GH"
fi

echo "Creating/updating secret/$SECRET..."
kubectl create secret generic "$SECRET" -n "$NS" \
  --from-literal=HIVE_HUB="$HUBS" \
  --from-literal=HIVE_REGISTRATION_TOKEN="$TOKENS" \
  --from-literal=GH_TOKEN="$GH" \
  "${CRED_ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Applying $MANIFEST..."
kubectl apply -f "$MANIFEST_DIR/$MANIFEST"

echo
echo "✓ $BACKEND deployed. Watch it come up:"
echo "  kubectl -n $NS rollout status deploy/${BACKEND/pi/pi-codex}-contributor"
echo "  kubectl -n $NS logs deploy/${BACKEND/pi/pi-codex}-contributor -c contributor --tail=20"
