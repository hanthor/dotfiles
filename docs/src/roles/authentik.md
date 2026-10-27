# authentik

**Historical Kubernetes migration (2026-06-12).**

The former Ansible role (Podman Quadlets on bihar) was removed. Its Kubernetes manifests are retained as historical recovery material; they do not establish that Authentik runs now. Bihar's OS and services are unverified, and Karnataka runs Utah.

See [`talos-k8s/authentik/`](https://github.com/hanthor/dotfiles/tree/master/talos-k8s/authentik) for the historical Helm-based manifest. Do not apply it to repurposed nodes.

Former Kubernetes URL: `https://auth.manatee-basking.ts.net` (historical, not a running endpoint).
