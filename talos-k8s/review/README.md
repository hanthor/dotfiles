# review — IndiaFOSS 2026 CFP review dashboard

Served at **https://review.manatee-basking.ts.net** (Tailscale Ingress, `default` ns).

A static SPA (`~/dev/indiafoss-2026-cfp/dashboard/`) plus a tiny stdlib Python
backend (`server.py`) that proxies to FossUnited so reviewers can post decisions
back using a server-held `sid`.

- `review.yaml` — Deployment + Service + Tailscale Ingress (host `review`).
- Image + Dockerfile live in the app repo: `~/dev/indiafoss-2026-cfp/deploy/`.

> **PII**: `data.json` + `avatars/` (speaker bios, names, faces) are baked into
> the image. Push **only** to the private Forgejo registry on the tailnet.

## Build & push (Forgejo registry)
```sh
cd ~/dev/indiafoss-2026-cfp
python3 cache_avatars.py && python3 build_dashboard.py        # refresh data + local avatars
podman login forgejo.manatee-basking.ts.net                   # one-time (Forgejo user/token)
podman build -f deploy/Dockerfile -t forgejo.manatee-basking.ts.net/james/cfp-dashboard:latest .
podman push forgejo.manatee-basking.ts.net/james/cfp-dashboard:latest
```

## Prerequisite: let the nodes resolve the Forgejo registry (one-time)
The Talos nodes can't resolve the tailnet MagicDNS name `forgejo.manatee-basking.ts.net`
for image pulls (`no such host`). Add a host entry pointing it at Forgejo's tailnet
IP (`100.88.105.60`) — keeps the real TLS cert, no reboot. **Run from a host that can
reach Talos apid `:50000`** (an allowlisted admin host, e.g. goa — apid is firewalled
off the general LAN/tailnet):
```sh
talosctl -e 192.168.0.5 -n 192.168.0.5,192.168.0.6 \
  patch mc --patch @talos-k8s/review/forgejo-host-patch.yaml
```
After this, the stuck `review-dashboard` pod recovers on its own (ImagePullBackOff retries).

## Deploy
```sh
kubectl apply -f ~/.local/share/dotfiles/talos-k8s/review/review.yaml
kubectl -n default rollout status deploy/review-dashboard
# pull secret, if the registry needs auth for the cluster to pull:
#   kubectl -n default create secret docker-registry forgejo-pull \
#     --docker-server=forgejo.manatee-basking.ts.net --docker-username=james --docker-password=… \
#   then add `imagePullSecrets: [{name: forgejo-pull}]` to the pod spec.
```

## Update after a data refresh
Rebuild + push the image, then:
```sh
kubectl -n default rollout restart deploy/review-dashboard
```

## Sign in / post reviews
Click the **● FOSS sign-in** badge in the dashboard top bar → paste your
fossunited.org `sid`. The backend verifies it and (once `REVIEW_ENDPOINT` is set
in `review.yaml`) forwards review decisions. The `sid` lives in an emptyDir, so
re-enter it after a pod restart.

## Notes
- `kubectl` from a tailnet machine needs `tls-server-name=192.168.0.5` on the
  cluster (the API cert lacks the tailnet IP) — handled by the dotfiles `kube`
  ansible role.
