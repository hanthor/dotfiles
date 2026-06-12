# authentik

SSO / identity provider. Serves `https://auth.manatee-basking.ts.net`.

## Deploy

```bash
# Create namespace (privileged for Longhorn volumes)
kubectl create ns authentik
kubectl label ns authentik pod-security.kubernetes.io/enforce=privileged --overwrite

# Generate secrets
AUTHENTIK_SECRET=$(openssl rand -base64 48)
PG_PASSWORD=$(openssl rand -base64 24)
kubectl create secret generic authentik-secret \
  --namespace authentik \
  --from-literal=secret-key="$AUTHENTIK_SECRET"
kubectl create secret generic authentik-postgres \
  --namespace authentik \
  --from-literal=password="$PG_PASSWORD"

# Install
helm repo add authentik https://charts.goauthentik.io
helm upgrade --install authentik authentik/authentik \
  --namespace authentik --values values.yaml
```

## Post-install

1. Access `https://auth.manatee-basking.ts.net/if/flow/initial-setup/`
2. Create the admin account
3. Configure OAuth2/OIDC providers for other services

## Backup

- PostgreSQL data on Longhorn volume, included in cluster snapshots
- Export flows/providers via Authentik API/UI backup
