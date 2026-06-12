# AppFlowy Cloud

Collaborative workspace. Serves `https://appflowy.manatee-basking.ts.net`.

Uses the official [AppFlowy Self-Host Commercial Helm chart](https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial/tree/main/helm).

## Architecture

Bundles PostgreSQL (pgvector) + Redis + MinIO + 5 app services:
- **GoTrue** — auth service
- **AppFlowy Cloud** — main backend (Rust)
- **AppFlowy Worker** — background jobs
- **AppFlowy Web** — frontend (nginx)
- **Admin Frontend** — admin console at `/console`

## Deploy

```bash
# Clone chart
git clone https://github.com/AppFlowy-IO/AppFlowy-SelfHost-Commercial.git /tmp/appflowy-chart

# Create namespace
kubectl create ns appflowy
kubectl label ns appflowy pod-security.kubernetes.io/enforce=privileged --overwrite

# Generate secrets
PG_PASSWORD=$(openssl rand -base64 24)
MINIO_PASSWORD=$(openssl rand -base64 24)
JWT_SECRET=$(openssl rand -base64 48)

# Deploy
cd /tmp/appflowy-chart/helm/appflowy-cloud
helm dependency update
helm upgrade --install appflowy . \
  --namespace appflowy \
  --values /home/james/.local/share/dotfiles/talos-k8s/appflowy/values-tailnet.yaml \
  --set global.postgresql.password="$PG_PASSWORD" \
  --set global.s3.secretKey="$MINIO_PASSWORD" \
  --set global.jwt.secret="$JWT_SECRET"
```

## Resource footprint (~2.7Gi RAM, ~24Gi disk)

| Service | Memory | Disk |
|---|---|---|
| PostgreSQL (pgvector) | 256Mi–512Mi | 10Gi |
| Redis | 64Mi–128Mi | 4Gi |
| MinIO | 128Mi–256Mi | 10Gi |
| GoTrue | 64Mi–256Mi | — |
| Cloud backend | 128Mi–512Mi | — |
| Worker | 128Mi–256Mi | — |
| Web frontend | 64Mi–128Mi | — |
| Admin frontend | 64Mi–128Mi | — |
