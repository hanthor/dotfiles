#!/usr/bin/env bash
# wire-kiro-key.sh — put the owner's Kiro API key into a hive namespace.
#
# Creates/updates Secret `kiro-api` (key KIRO_API_KEY) from the Bitwarden
# secure note `kiro-api-key`, then adds
#   env KIRO_API_KEY <- secretKeyRef kiro-api/KIRO_API_KEY (optional)
# to container `hive` of Deployment `hive`, unless it is already there.
# The hive's tmux server inherits the container env, so every agent's `pi`
# sees it; the pi-kiro-api provider (hive-pi-kiro.sh) reads it.
#
# Adding the env var changes the pod template, and the hive Deployments use the
# Recreate strategy: THIS RESTARTS THE HIVE POD. Do one namespace at a time and
# check /api/health between them. hive and hive-reef share one GitHub App
# installation (and its rate limit): leave ~10 minutes between their restarts.
#
# The key never touches argv, git, or a persistent disk: it goes from `bw`
# into a mode-600 file on /dev/shm, `kubectl --from-env-file` reads it, and the
# file is shredded. hive-upgrade's strategic-merge patch only sets `image`, so it
# keeps this env entry.
#
# USAGE: wire-kiro-key.sh <namespace>   (run from the dotfiles checkout, BW unlockable)
set -euo pipefail
ns="${1:?usage: $0 <namespace>}"
: "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"; export KUBECONFIG
repo=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)

eval "$("$repo/scripts/bw-resolve.sh" local)" >/dev/null
f=$(mktemp -p /dev/shm kiro.XXXXXX); chmod 600 "$f"
trap 'shred -u "$f" 2>/dev/null || rm -f "$f"' EXIT
key=$(bw get notes kiro-api-key | tr -d '[:space:]')
[ -n "$key" ] || { echo "ERROR: Bitwarden note kiro-api-key is empty" >&2; exit 1; }
printf 'KIRO_API_KEY=%s\n' "$key" > "$f"; unset key
kubectl -n "$ns" create secret generic kiro-api --from-env-file="$f" \
  --dry-run=client -o yaml | kubectl -n "$ns" apply -f - >/dev/null
echo "$ns: secret kiro-api applied"

idx=$(kubectl -n "$ns" get deploy hive -o json \
      | jq '.spec.template.spec.containers | map(.name) | index("hive")')
[ "$idx" != null ] || { echo "ERROR: no container 'hive' in $ns/hive" >&2; exit 1; }
if kubectl -n "$ns" get deploy hive -o json \
     | jq -e --argjson i "$idx" '.spec.template.spec.containers[$i].env // [] | any(.name=="KIRO_API_KEY")' >/dev/null; then
  echo "$ns: env KIRO_API_KEY already wired — no restart"
  exit 0
fi
kubectl -n "$ns" patch deploy hive --type json -p "$(jq -cn --argjson i "$idx" '[{op:"add",
  path:"/spec/template/spec/containers/\($i)/env/-",
  value:{name:"KIRO_API_KEY",valueFrom:{secretKeyRef:{name:"kiro-api",key:"KIRO_API_KEY",optional:true}}}}]')"
echo "$ns: env wired — pod restarting (Recreate)"
kubectl -n "$ns" rollout status deploy/hive --timeout=600s
