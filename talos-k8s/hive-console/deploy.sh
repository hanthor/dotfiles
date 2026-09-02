#!/usr/bin/env bash
# deploy.sh — (re)deploy hive-console.
#
# app.py lives as a real file in git (readable, lintable, diffable) and is
# turned into a ConfigMap here rather than being pasted into YAML. The
# Deployment carries a checksum annotation of app.py so that changing the code
# actually rolls the pod — a bare `kubectl apply` of a new ConfigMap otherwise
# leaves the old code running until someone remembers to restart it.
set -euo pipefail

: "${KUBECONFIG:=$HOME/.kube/config-aws-migration}"
export KUBECONFIG

cd "$(dirname "$0")"

echo "==> publishing app.py as configmap/hive-console-app"
kubectl create configmap hive-console-app -n hive \
  --from-file=app.py=app.py \
  --dry-run=client -o yaml | kubectl apply -f -

SUM=$(sha256sum app.py | cut -c1-16)
echo "==> applying manifests (app checksum $SUM)"
sed "s/REPLACED_AT_DEPLOY/$SUM/" console.yaml | kubectl apply -f -

echo "==> waiting for rollout"
kubectl rollout status deploy/hive-console -n hive --timeout=180s

echo
echo "console: https://hive.tunaos.org/console"
echo "(sign in at https://hive.tunaos.org first — the console shares that session)"
