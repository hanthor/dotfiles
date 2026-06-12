# n8n

Workflow automation. Serves `https://n8n.manatee-basking.ts.net`.

## Deploy

```bash
kubectl create ns n8n
kubectl label ns n8n pod-security.kubernetes.io/enforce=privileged --overwrite

# Generate encryption key
N8N_KEY=$(openssl rand -base64 32)
kubectl create secret generic n8n-secret \
  --namespace n8n \
  --from-literal=encryption-key="$N8N_KEY"

kubectl apply -f manifest.yaml
```

## Post-install

1. Access `https://n8n.manatee-basking.ts.net`
2. Create owner account on first visit
3. Start building workflows

## Notes

- Uses SQLite on a Longhorn volume — simple, no external DB needed
- Encryption key is stored in a K8s secret, not committed to git
- No Helm chart needed — plain K8s manifest
