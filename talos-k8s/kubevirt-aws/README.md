# KubeVirt on the AWS cluster (tailnet-only corral)

A Proxmox-style VM host on the AWS Talos cluster: KubeVirt VMs on a
dedicated node, managed through corral-web at `https://corral-aws.<tailnet>.ts.net`.
There is no public ingress; the node has no public services, and corral-web is
published only through the Tailscale operator.

| Piece | Where |
|---|---|
| Node: m7i.2xlarge with nested virtualization, tainted for VMs only | `aws/kubevirt.tf` |
| Spend kill switch: AWS Budgets stops the node at $1100 gross/month | `aws/kubevirt.tf` |
| Idle stop after 30 minutes with no VM pods | `idle-stop.yaml` |
| Start on demand | `scripts/kubevirt-node up` |
| KubeVirt/CDI placement (infra on always-on nodes, VMs on the node) | `kubevirt-cr.yaml` |
| corral-web as `corral-aws` on the tailnet | `kustomization.yaml` |

**Cost:** $0.4284/h while running (~$313/month if it never stopped) plus
150 GB gp3 (~$13/month). Stopped, it costs only the disk. At the time of
writing (2026-09-24) gross spend forecast was ~$364/month against $1400/month
credits.

## Bring-up (once)

```bash
export KUBECONFIG=~/.kube/config-aws-migration TALOSCONFIG=~/.talos/config-aws-migration

# 1. Node (boots Talos in maintenance mode: no user_data, no secrets in state)
cd aws && tofu plan -out tfplan && tofu apply tfplan && cd ..
IP=$(cd aws && tofu output -raw kubevirt_public_ip)

# 2. Join it: the existing worker's config + the kubevirt patch. /tmp only, never commit.
talosctl -n 10.20.1.11 get machineconfig -o jsonpath='{.spec}' > /tmp/worker.yaml
talosctl machineconfig patch /tmp/worker.yaml --patch @talos-k8s/kubevirt-aws/talos-patch.yaml -o /tmp/kubevirt.yaml
talosctl apply-config --insecure -e "$IP" -n "$IP" -f /tmp/kubevirt.yaml
shred -u /tmp/worker.yaml /tmp/kubevirt.yaml
kubectl wait --for=condition=Ready node -l tunaos.org/kubevirt=true --timeout=15m
talosctl -n 10.20.1.12 ls /dev | grep kvm          # must list kvm

# 3. KubeVirt + CDI operators, then our placement/config
kubectl apply -f https://github.com/kubevirt/kubevirt/releases/download/v1.8.2/kubevirt-operator.yaml
kubectl apply -f https://github.com/kubevirt/containerized-data-importer/releases/download/v1.66.1/cdi-operator.yaml
kubectl apply -f talos-k8s/kubevirt-aws/kubevirt-cr.yaml
kubectl -n kubevirt wait kv kubevirt --for condition=Available --timeout=15m

# 4. Idle-stop credentials (scoped IAM user from aws/kubevirt.tf), then corral-web + CronJob.
#    The key already exists: Bitwarden secure note `kubevirt-node-power`
#    (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / INSTANCE_ID / AWS_DEFAULT_REGION).
#    Only if it is lost: aws iam create-access-key --user-name kubevirt-node-power
for ns in kubevirt-aws tailvm; do kubectl create namespace $ns --dry-run=client -o yaml | kubectl apply -f -
kubectl -n $ns create secret generic node-power \
  --from-literal=AWS_ACCESS_KEY_ID=... --from-literal=AWS_SECRET_ACCESS_KEY=... \
  --from-literal=INSTANCE_ID="$(cd aws && tofu output -raw kubevirt_instance_id)"; done
kubectl kustomize --load-restrictor LoadRestrictionsNone talos-k8s/kubevirt-aws | kubectl apply -f -
```

## Day to day

```bash
scripts/kubevirt-node up        # ~2 min; the node stops itself after 30 idle minutes
corral --context aws-migration list   # or https://corral-aws.<tailnet>.ts.net
scripts/kubevirt-node down      # stop now
```

## Caveats

- Nested virtualization costs some CPU performance. It's fine for test VMs
  and CI, but not for heavy builds.
- Stopping the node stops its VMs. Disks persist, because the root volume
  survives a stop, but anything in RAM is lost. `down` shuts VMs down first;
  idle-stop only fires when no VMs are running.
- The public IP changes on every start. Nothing depends on it after the join:
  the node reaches the control plane over the VPC.
