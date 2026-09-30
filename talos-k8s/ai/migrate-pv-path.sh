#!/bin/bash
# migrate-pv-path.sh — one-time migration of Lemonade PV hostPaths from
# /var/tmp to /var/lib on karnataka (dotfiles#29).
#
# WHY THIS IS MANUAL: this script only moves data on disk. It does not
# touch the cluster. Run it BEFORE applying the updated lemonade.yaml —
# recreating the PVs against the new hostPath while the old path still
# holds the data would silently orphan 100+ GB of downloaded models
# (Kubernetes does not move hostPath data when you edit a PV spec).
#
# Run this ON karnataka (the Talos worker node), not from this repo's
# checkout on a workstation.
#
# Sequence (matches the plan in dotfiles#29):
#   1. Stop the lemonade pod so nothing is writing to the old path.
#   2. Move the data on disk.
#   3. Delete the old PV/PVC and apply the updated lemonade.yaml
#      (already changed in this PR) so the PVs point at /var/lib.
#   4. Recreate the pod.
set -euo pipefail

OLD_MODELS=/var/tmp/lemonade-models
OLD_CACHE=/var/tmp/lemonade-cache
NEW_MODELS=/var/lib/lemonade-models
NEW_CACHE=/var/lib/lemonade-cache

echo "== Step 1: scale down the lemonade deployment =="
kubectl scale deployment/lemonade --replicas=0
kubectl wait --for=delete pod -l app=lemonade --timeout=60s || true

echo "== Step 2: move data on disk (karnataka only) =="
for pair in "$OLD_MODELS:$NEW_MODELS" "$OLD_CACHE:$NEW_CACHE"; do
  src="${pair%%:*}"
  dst="${pair##*:}"
  if [ ! -d "$src" ]; then
    echo "  skip: $src does not exist"
    continue
  fi
  if [ -e "$dst" ]; then
    echo "  ERROR: $dst already exists — refusing to overwrite. Resolve manually." >&2
    exit 1
  fi
  echo "  mv $src -> $dst"
  mv "$src" "$dst"
done

echo "== Step 3: recreate PVs/PVCs against the new hostPath =="
echo "  (apply the updated talos-k8s/ai/lemonade.yaml from this PR before continuing)"
kubectl delete pvc lemonade-models lemonade-cache --ignore-not-found
kubectl delete pv lemonade-models-pv lemonade-cache-pv --ignore-not-found
kubectl apply -f talos-k8s/ai/lemonade.yaml

echo "== Step 4: scale the deployment back up =="
kubectl scale deployment/lemonade --replicas=1

echo "Done. Verify with:"
echo "  kubectl get pv,pvc"
echo "  kubectl exec -n default deploy/lemonade -- du -sh /opt/lemonade/llama /root/.cache/huggingface"
