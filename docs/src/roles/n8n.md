# n8n

**Historical Kubernetes migration (2026-06-12).**

The former Ansible role (Podman Quadlet on bihar) was removed. Its Kubernetes manifests are retained as historical recovery material; they do not establish that n8n runs now. Bihar's OS and services are unverified, and Karnataka runs Utah.

See [`talos-k8s/n8n/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s/n8n) for the historical Kubernetes manifest. Do not apply it to repurposed nodes.

Former Kubernetes URL: `https://n8n.manatee-basking.ts.net` (historical, not a running endpoint).
