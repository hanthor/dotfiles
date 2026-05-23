#!/bin/bash
set -eo pipefail

# Secure Ignition Generator for Karnataka
# Dynamically injects Tailscale secrets from Bitwarden without checking them into Git.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
TEMPLATE_FILE="${SCRIPT_DIR}/karnataka-fresh.bu.tmpl"
PXE_OUTPUT_DIR="/var/lib/pxe/http"
OUTPUT_FILE="${PXE_OUTPUT_DIR}/karnataka-fresh.ign"

# BW CLI Path
BW_PATH="/home/linuxbrew/.linuxbrew/bin/bw"
BITWARDEN_ITEM_ID="8541782c-edbb-4b57-9218-b2bb00aeed3b" # tailscale k8s operator

# Check Bitwarden Session
if [ -z "${BW_SESSION}" ]; then
    echo "ERROR: Bitwarden session is not active. Please unlock your vault first:"
    echo "  export BW_SESSION=\$(bw unlock --raw)"
    exit 1
fi

if [ ! -f "${TEMPLATE_FILE}" ]; then
    echo "ERROR: Template file not found at ${TEMPLATE_FILE}"
    exit 1
fi

echo "Retrieving Tailscale operator client secret from Bitwarden..."
TS_AUTHKEY=$("${BW_PATH}" get item "${BITWARDEN_ITEM_ID}" | jq -r '.fields[] | select(.name=="Client Secret") | .value')

if [ -z "${TS_AUTHKEY}" ] || [ "${TS_AUTHKEY}" == "null" ]; then
    echo "ERROR: Failed to retrieve Tailscale auth key from Bitwarden."
    exit 1
fi

echo "Generating temporary Butane file..."
TMP_BU=$(mktemp /tmp/karnataka-fresh.XXXXXX.bu)
trap 'rm -f "${TMP_BU}"' EXIT

# Substitute placeholder
sed "s/{{TS_AUTHKEY}}/${TS_AUTHKEY}/g" "${TEMPLATE_FILE}" > "${TMP_BU}"

echo "Transpiling Butane template to Ignition JSON using Podman..."
TMP_IGN=$(mktemp /tmp/karnataka-fresh.XXXXXX.ign)
trap 'rm -f "${TMP_BU}" "${TMP_IGN}"' EXIT

# Run Butane in Podman
if ! podman run --interactive --rm quay.io/coreos/butane:release < "${TMP_BU}" > "${TMP_IGN}"; then
    echo "ERROR: Butane transpilation failed."
    exit 1
fi

echo "Writing secure Ignition config directly to PXE directory: ${OUTPUT_FILE}..."
if [ ! -d "${PXE_OUTPUT_DIR}" ]; then
    echo "ERROR: PXE HTTP directory ${PXE_OUTPUT_DIR} does not exist on this host."
    exit 1
fi

# Move file using sudo since /var/lib/pxe/http is system-owned
sudo cp "${TMP_IGN}" "${OUTPUT_FILE}"
sudo chmod 644 "${OUTPUT_FILE}"

echo "========================================================="
echo " SUCCESS: karnataka-fresh.ign generated securely!"
echo " Serving at: http://192.168.0.5:8888/karnataka-fresh.ign"
echo " (No secrets were checked into Git)"
echo "========================================================="
