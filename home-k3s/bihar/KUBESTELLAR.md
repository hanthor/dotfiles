# Bihar k3s + KubeStellar hub

k3s v1.36.5 single-node server on bihar tailnet IP 100.103.44.48 (install-host.sh, config.yaml).
- service-cidr 10.96.0.0/12: KubeFlex vcluster ITS hard-codes the kind range; k3s default 10.43/16 breaks it.
- firewalld: cni0 in zone internal, pod->kubelet 10250 rule, policy k3s-pod-egress (internal->public).
  Without these, metrics-server fails (discovery breaks KubeFlex hooks) and pod DNS/egress fails.

KubeStellar core chart 0.30.2 (helm release ks-core, ns default):
  domain 100.103.44.48.sslip.io, externalPort 9443 (ingress-nginx hostPort, SSL passthrough, tailnet-only)
  ITS its1 (vcluster) https://its1.100.103.44.48.sslip.io:9443
  WDS wds1 (k8s)      https://wds1.100.103.44.48.sslip.io:9443
kubectl contexts: bihar, its1, wds1 (~/.kube/config).

WECs (clusteradm 1.0.0, --singleton): bihar, karnataka. Labels: location-group=home, name=<host>,
  bihar: cpu=intel role=hub; karnataka: cpu=amd gpu=amd kubevirt=true
Join token cmd: ~/.kube/its1-join.cmd (secret). Karnataka joined via its k3s.yaml pointed at 100.66.158.127.

Deploy: apply objects to --context wds1 plus a BindingPolicy (clusterSelectors on labels);
add wantSingletonReportedState: true to get status back when bound to one cluster.
