#!/usr/bin/env bash
# deploy.sh — (re)deploy the in-cluster hive operations control plane.
#
# The scripts keep their canonical home in roles/hive_ops/files/bin/ and are
# published into a ConfigMap here, rather than duplicated into YAML. One copy,
# still shellcheck-able and diffable, and `just apply-tags hive_ops` and this
# script cannot drift apart.
set -euo pipefail

: "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
export KUBECONFIG

cd "$(dirname "$0")/../.."   # repo root
BIN=roles/hive_ops/files/bin

for f in hive-rotate.sh hive-peak.sh hive-repo-sync.sh hive-metrics.sh \
         hive-fork-drift.sh hive-tiers.sh hive-pace.sh hive-inventory.sh hive-fork-ai-check.sh hive-fork-switch.sh \
         hive-cli-update.sh hive-shared-auth.sh; do
  [ -f "$BIN/$f" ] || { echo "missing $BIN/$f" >&2; exit 1; }
  bash -n "$BIN/$f" || { echo "syntax error in $f" >&2; exit 1; }
done

echo "==> publishing scripts as configmap/hive-ops-scripts"
kubectl create configmap hive-ops-scripts -n hive \
  --from-file=hive-rotate.sh="$BIN/hive-rotate.sh" \
  --from-file=hive-peak.sh="$BIN/hive-peak.sh" \
  --from-file=hive-repo-sync.sh="$BIN/hive-repo-sync.sh" \
  --from-file=hive-metrics.sh="$BIN/hive-metrics.sh" \
  --from-file=hive-fork-drift.sh="$BIN/hive-fork-drift.sh" \
  --from-file=hive-tiers.sh="$BIN/hive-tiers.sh" \
  --from-file=hive-pace.sh="$BIN/hive-pace.sh" \
  --from-file=hive-inventory.sh="$BIN/hive-inventory.sh" \
  --from-file=hive-fork-ai-check.sh="$BIN/hive-fork-ai-check.sh" \
  --from-file=hive-fork-switch.sh="$BIN/hive-fork-switch.sh" \
  --from-file=hive-cli-update.sh="$BIN/hive-cli-update.sh" \
  --from-file=hive-shared-auth.sh="$BIN/hive-shared-auth.sh" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> applying manifests"
kubectl apply -f talos-k8s/hive-ops/hive-ops.yaml

echo
kubectl get cronjob -n hive -l app.kubernetes.io/name=hive-ops \
  -o custom-columns='NAME:.metadata.name,SCHEDULE:.spec.schedule,SUSPEND:.spec.suspend,LAST:.status.lastScheduleTime'
echo
echo "Run one now:   kubectl create job -n hive adhoc-\$(date +%s) --from=cronjob/hive-rotate"
echo "Watch a run:   kubectl logs -n hive -l app.kubernetes.io/component=rotate --tail=50"
