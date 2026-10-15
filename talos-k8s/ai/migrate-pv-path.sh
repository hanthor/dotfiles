#!/bin/bash
# migrate-pv-path.sh — one-time migration of Lemonade PV hostPaths from
# /var/tmp to /var/lib on karnataka (dotfiles#29).
#
# Run BEFORE applying the updated lemonade.yaml: recreating the PVs against
# the new hostPath while the old path still holds the data would silently
# orphan 100+ GB of downloaded models (Kubernetes does not move hostPath data
# when you edit a PV spec).
#
# Run from a workstation with the home-cluster kubeconfig. Talos has no shell,
# so the on-disk move runs in a `kubectl debug node/` pod (sysadmin profile,
# host root mounted at /host).
#
# Sequence (matches the plan in dotfiles#29):
#   1. Stop the lemonade pod so nothing is writing to the old path.
#   2. Move the data on disk.
#   3. Delete the old PV/PVC and apply lemonade.yaml (already /var/lib).
#   4. Recreate the pod.
set -euo pipefail

NODE=${NODE:-karnataka}

echo "== Step 1: scale down the lemonade deployment =="
kubectl scale deployment/lemonade --replicas=0
kubectl wait --for=delete pod -l app=lemonade --timeout=60s || true

echo "== Step 2: move data on disk ($NODE) =="
move='set -e
for pair in /var/tmp/lemonade-models:/var/lib/lemonade-models /var/tmp/lemonade-cache:/var/lib/lemonade-cache; do
  src=/host${pair%%:*}; dst=/host${pair##*:}
  if [ ! -d "$src" ]; then echo "  skip: $src does not exist"; continue; fi
  if [ -e "$dst" ]; then echo "  ERROR: $dst already exists, refusing to overwrite" >&2; exit 1; fi
  echo "  mv $src -> $dst"; mv "$src" "$dst"
done
echo MOVE-OK'
# kube-system: Talos exempts it from Pod Security admission, which would
# otherwise reject the privileged debug pod.
out=$(kubectl debug "node/$NODE" -n kube-system --profile=sysadmin --image=busybox:1.37 --attach --quiet -- sh -c "$move" 2>&1) || true
echo "$out"
kubectl -n kube-system get pods -o name | grep "node-debugger-$NODE-" | xargs -r kubectl -n kube-system delete --wait=false >/dev/null
if ! grep -q MOVE-OK <<<"$out"; then
  echo "Move did not complete; the deployment is left scaled to 0. Resolve, then re-run." >&2
  exit 1
fi

echo "== Step 3: recreate PVs/PVCs against the new hostPath =="
kubectl delete pvc lemonade-models lemonade-cache --ignore-not-found
kubectl delete pv lemonade-models-pv lemonade-cache-pv --ignore-not-found
kubectl apply -f "$(dirname "$0")/lemonade.yaml"

echo "== Step 4: scale the deployment back up =="
kubectl scale deployment/lemonade --replicas=1

echo "Done. Verify with:"
echo "  kubectl get pv,pvc"
echo "  kubectl exec -n default deploy/lemonade -- du -sh /opt/lemonade/llama /root/.cache/huggingface"
