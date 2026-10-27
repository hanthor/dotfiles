#!/usr/bin/env bash
# Run as root on Karnataka, against this cluster only. Upstream asset digests
# are from the GitHub release metadata; the Corral image is pinned by digest.
# Server-side apply fails on ownership conflicts rather than forcing over live
# settings. Apply is not transactional; review any conflict before retrying.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(hostname -s)" = karnataka ] || { echo 'Wrong host' >&2; exit 1; }
k=(/var/usrlocal/bin/k3s kubectl --kubeconfig /etc/rancher/k3s/k3s.yaml --server https://100.66.158.127:6443)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
fetch() {
  local name=$1 hash=$2 url=$3
  curl -fsSL --retry 3 "$url" -o "$tmp/$name"
  printf '%s  %s\n' "$hash" "$tmp/$name" | sha256sum -c -
}
fetch kubevirt-operator.yaml 9ac45a436c49d32e6fc21d542bcb7600b970705297b9e6752f3ef9b0a1d292da https://github.com/kubevirt/kubevirt/releases/download/v1.9.1/kubevirt-operator.yaml
fetch kubevirt-cr.yaml 43106136dbce3312bdbfdeae612aacafc6c12da518d233f90645b4685d84a2af https://github.com/kubevirt/kubevirt/releases/download/v1.9.1/kubevirt-cr.yaml
fetch cdi-operator.yaml c7d92bd1b2ee1a3952a5990000437c08d58109f31c0bd48ab6188ec27a13e224 https://github.com/kubevirt/containerized-data-importer/releases/download/v1.66.1/cdi-operator.yaml
fetch cdi-cr.yaml a497f90de608c1df26f9ee4095289373f17132d74a2042ca03e00c17c964f8a7 https://github.com/kubevirt/containerized-data-importer/releases/download/v1.66.1/cdi-cr.yaml
"${k[@]}" apply --server-side --field-manager=home-k3s -f "$tmp/kubevirt-operator.yaml"
"${k[@]}" wait --for=condition=Established --timeout=120s crd/kubevirts.kubevirt.io
"${k[@]}" apply --server-side --field-manager=home-k3s -f "$tmp/kubevirt-cr.yaml"
"${k[@]}" wait -n kubevirt kubevirt/kubevirt --for=condition=Available --timeout=10m
"${k[@]}" apply --server-side --field-manager=home-k3s -f "$tmp/cdi-operator.yaml"
"${k[@]}" wait --for=condition=Established --timeout=120s crd/cdis.cdi.kubevirt.io
"${k[@]}" apply --server-side --field-manager=home-k3s -f "$tmp/cdi-cr.yaml"
"${k[@]}" wait cdi/cdi --for=condition=Available --timeout=10m
"${k[@]}" wait --for=create --timeout=120s storageprofile/local-path
"${k[@]}" apply --server-side --field-manager=home-k3s -f local-path-profile.yaml
"${k[@]}" apply --server-side --field-manager=home-k3s -f corral-web.yaml
