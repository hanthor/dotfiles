#!/bin/bash
set -eo pipefail

# Deployment Script for KubeVirt Manager on Karnataka
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
KARNATAKA_IP="192.168.0.6"

echo "========================================================="
echo " Deploying KubeVirt Manager Web UI to Karnataka over SSH..."
echo "========================================================="

# Apply KubeVirt Manager core components and Ingress
cat "${SCRIPT_DIR}/bundled.yaml" "${SCRIPT_DIR}/ingress.yaml" | ssh core@${KARNATAKA_IP} "kubectl apply -f -"

echo "========================================================="
echo " Deployment Manifests Applied Successfully!"
echo "========================================================="
echo "To monitor the status of the pods, run:"
echo "  ssh core@${KARNATAKA_IP} \"kubectl get pods -n kubevirt-manager -w\""
echo ""
echo "Secure URL on your Tailnet:"
echo "  https://vm.manatee-basking.ts.net"
echo "========================================================="
