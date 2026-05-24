#!/bin/bash
set -eo pipefail

# Deployment Helper Script for vLLM ROCm on Karnataka
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
KARNATAKA_IP="192.168.0.6"

echo "========================================================="
echo " Deploying vLLM ROCm to Karnataka over SSH..."
echo "========================================================="

# Apply namespace first and wait
ssh core@${KARNATAKA_IP} "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl apply -f -" < "${SCRIPT_DIR}/00-namespace.yaml"
sleep 1

# Apply the rest of the manifests
cat "${SCRIPT_DIR}/00-amd-gpu-device-plugin.yaml" \
    "${SCRIPT_DIR}/01-pvc.yaml" \
    "${SCRIPT_DIR}/02-deployment-rocm.yaml" \
    "${SCRIPT_DIR}/03-service.yaml" \
    "${SCRIPT_DIR}/04-ingress.yaml" | ssh core@${KARNATAKA_IP} "sudo KUBECONFIG=/etc/kubernetes/admin.conf kubectl apply -f -"

echo "========================================================="
echo " Manifests applied successfully!"
echo "========================================================="
echo "To monitor the status of the vLLM deployment, run:"
echo "  ssh core@${KARNATAKA_IP} \"kubectl get pods -n vllm -w\""
echo ""
echo "Note: The deployment requires active GPU device mapping."
echo "Ensure the AMD GPU device plugin is deployed in your cluster."
echo "Once the pod is running, test the endpoint on your Tailnet:"
echo "  curl http://vllm.manatee-basking.ts.net/v1/models"
echo "========================================================="
