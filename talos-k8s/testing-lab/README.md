# Bluefin Testing Lab — adapted for this cluster

QA pipeline adapted from [projectbluefin/testing-lab](https://github.com/projectbluefin/testing-lab).

## Architecture

```
┌───────────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  PR Scanner           │────▶│  QA Pipeline      │────▶│  GitHub Status     │
│  (every 30 min)       │     │  (Argo Workflows)  │     │  (future)         │
│                       │     │                    │     │                    │
│  GitHub API → open PRs│     │  BIB → golden disk │     │  pending/success   │
│  Filter tested        │     │  Reflink → VM      │     │  /failure          │
│  Submit workflows     │     │  behave/dogtail    │     │                    │
└───────────────────────┘     │  Teardown          │     └────────────────────┘
                              └──────────────────┘
```

## Components

| File | Description |
|------|-------------|
| `workflow-templates/bib-build-and-push.yaml` | BIB golden disk builder (pull → build → configure → store) |
| `workflow-templates/provision-vm.yaml` | Reflink clone + KubeVirt hostDisk VM |
| `workflow-templates/run-gnome-tests.yaml` | behave + qecore + dogtail test runner |
| `workflow-templates/teardown-vm.yaml` | Clean up VM + hostDisk |
| `workflow-templates/bluefin-qa-pipeline.yaml` | Full pipeline DAG |
| `workflow-templates/bluefin-test-matrix.yaml` | Parallel latest + lts test run |
| `pr-scanner-cron.yaml` | CronWorkflow scanning open PRs every 30 min |

## Environment-agnostic design

All templates use `compute-node` parameter (default: `karnataka`) instead of hardcoded node names.
See upstream issues: [#149](https://github.com/projectbluefin/testing-lab/issues/149), [#150](https://github.com/projectbluefin/testing-lab/issues/150), [#151](https://github.com/projectbluefin/testing-lab/issues/151).

## Quick start

```bash
# Deploy everything
kubectl apply -f talos-k8s/testing-lab/workflow-templates/
kubectl apply -f talos-k8s/testing-lab/pr-scanner-cron.yaml

# Manual test run
argo submit --from workflowtemplate/bluefin-qa-pipeline \
  -n argo -p image-tag=latest --watch

# Trigger PR scanner now
argo submit --from cronworkflow/pr-scanner -n argo --watch

# Check status
kubectl get workflowtemplate -n argo
kubectl get cronworkflow -n argo
argo list -n argo
```

## Prerequisites

- [x] Argo Workflows v4 (installed in `argo` ns)
- [x] ArgoCD v2 (installed in `argocd` ns)
- [x] KubeVirt v1.8+ with HostDisk feature gate
- [x] SSH key secret (`bluefin-test-ssh-key` in `argo` ns)
- [x] GitHub token secret (`github-token` in `argo` ns)
- [x] Namespaces: `bluefin-test`, `bluefin-lts-test` (privileged PodSecurity)
- [ ] Golden disk built (first run will build automatically)
