# Home k3s and KubeStellar

bihar and karnataka each run a **separate single-node k3s** on Bluefin. They
replace the two-node Talos cluster ([archive](../archive/talos-k8s.md)).
**KubeStellar** on bihar connects the two clusters. The hosts are not on the same
LAN, so all cluster traffic uses the tailnet.

The kits are in [`home-k3s/`](https://github.com/hanthor/dotfiles/tree/master/home-k3s):
`bihar/` and `karnataka/` each contain `install-host.sh`, `config.yaml`,
`k3s.service`, `wait-tailnet.sh` and `resolv.conf`.

## Shared design

- The k3s binary is in `/var/usrlocal/bin/k3s`. `/usr` is read-only on bootc.
  `k3s.service` waits for the tailnet (`k3s-wait-tailnet`).
- The API server, kubelet and node IP bind to the **tailnet IP only**.
  Flannel uses `tailscale0`.
- traefik and servicelb are disabled. Services are exposed with `tailscale serve`
  (karnataka) or ingress-nginx (bihar, KubeStellar only).
- Pod DNS uses `resolv.conf` (1.1.1.1 and 1.0.0.1).
- SELinux on the host stays enforcing. The k3s SELinux module cannot be installed
  on bootc.

### firewalld (required: without these rules metrics-server fails and pods cannot resolve DNS)

```bash
# cni0 goes in the internal zone; pods can reach the kubelet
firewall-cmd --permanent --zone=internal --change-interface=cni0
firewall-cmd --permanent --zone=internal --add-rich-rule='rule family=ipv4 source address=10.42.0.0/16 destination address=<tailnet-ip>/32 port port=10250 protocol=tcp accept'
# pods can reach the internet
firewall-cmd --permanent --new-policy k3s-pod-egress
firewall-cmd --permanent --policy k3s-pod-egress --set-target CONTINUE
firewall-cmd --permanent --policy k3s-pod-egress --add-ingress-zone internal
firewall-cmd --permanent --policy k3s-pod-egress --add-egress-zone public
firewall-cmd --permanent --policy k3s-pod-egress --add-rich-rule='rule family=ipv4 source address=10.42.0.0/16 accept'
# API (and KubeStellar on bihar) from the tailnet only
firewall-cmd --permanent --zone=public --add-rich-rule='rule family=ipv4 source address=100.64.0.0/10 destination address=<tailnet-ip>/32 port port=6443 protocol=tcp accept'
```

bihar's `install-host.sh` applies these rules. On karnataka the rules were applied
by hand.

### Differences

| | bihar | karnataka |
|---|---|---|
| service CIDR | `10.96.0.0/12` (KubeFlex's vcluster hard-codes the kind range) | k3s default `10.43.0.0/16` |
| Extras | ingress-nginx (SSL passthrough), KubeFlex, KubeStellar | KubeVirt, CDI, ARC, workloads (see [Karnataka](karnataka.md)) |
| Reset | `reset-k3s.sh` | none |

## KubeStellar (hub on bihar)

KubeStellar 0.30.2 core chart (`oci://ghcr.io/kubestellar/kubestellar/core-chart`):

- **ITS `its1`:** vcluster with the OCM cluster-manager.
- **WDS `wds1`:** where you apply workloads.
- Both are served at `https://<name>.100.103.44.48.sslip.io:9443`. Port 9443 is open
  to the tailnet only.
- kubectl contexts on bihar: `bihar`, `its1`, `wds1` (in `~/.kube/config`).
- The join command is in `bihar:~/.kube/its1-join.cmd`. **It is a secret.**

Workload execution clusters (joined with `clusteradm` 1.0.0 `--singleton`):

| Cluster | Labels |
|---|---|
| bihar | `location-group=home name=bihar cpu=intel role=hub` |
| karnataka | `location-group=home name=karnataka cpu=amd gpu=amd kubevirt=true` |

Use it like this: apply manifests with `kubectl --context wds1`, and add a
`BindingPolicy` with a `clusterSelectors` label match. Set
`wantSingletonReportedState: true` to get status back from one cluster. Notes are
in [`home-k3s/bihar/KUBESTELLAR.md`](https://github.com/hanthor/dotfiles/blob/master/home-k3s/bihar/KUBESTELLAR.md).

### Problems found during installation (2026-11-17)
- If metrics-server is not ready, the KubeFlex hooks fail with "stale GroupVersion
  discovery". Correct the firewall, then restart `kubeflex-controller-manager`.
- A failed `ks-core` release stopped on the uninstall-postgresql hook. To recover,
  run `helm uninstall ks-core --no-hooks`, delete the `kubeflex-system`,
  `its1-system` and `wds1-system` namespaces, then install again.
