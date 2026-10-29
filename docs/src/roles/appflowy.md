# appflowy

**Historical Kubernetes migration (2026-06-12).**

The former Ansible role (Podman Quadlets on bihar) was removed. Its Kubernetes manifests are retained as historical recovery material; they do not establish that AppFlowy runs now. Bihar's OS and services are unverified, and Karnataka runs Utah.

See [`talos-k8s/appflowy/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s/appflowy) for the historical commercial Helm chart manifest. Do not apply it to repurposed nodes.

Former Kubernetes URL: `https://appflowy.manatee-basking.ts.net` (historical, not a running endpoint).
