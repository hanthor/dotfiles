# talosctl / kubectl over the tailnet

The API certs are auto-generated with the nodes' **LAN** IPs in their SANs, not
their tailnet IPs — so connecting over the tailnet fails verification:

```
tls: failed to verify certificate: x509: certificate is valid for 192.168.0.5, …, not 100.109.168.109
```

## kubectl — already fixed
The `kube` ansible role pins `tls-server-name=192.168.0.5` on the cluster in
kubeconfig (verifies against a real SAN while dialing the tailnet IP). Works today
from any tailnet machine, no cluster change needed.

## talosctl — needs a one-time cluster apply
`talosctl` has no `tls-server-name` override, so the proper fix is to add the
tailnet IPs/names to the node cert SANs. Already added to the GitOps source:

- `controlplane.yaml` → `machine.certSANs` + `cluster.apiServer.certSANs`: `100.109.168.109`, `bihar.manatee-basking.ts.net`
- `worker.yaml` → `machine.certSANs`: `100.123.30.57`, `karnataka.manatee-basking.ts.net`

Apply from a host that can reach Talos apid `:50000` (an allowlisted admin host
on the LAN, e.g. **goa** — apid is firewalled off the general LAN/tailnet):

```sh
talosctl -e 192.168.0.5 -n 192.168.0.5 apply-config -f controlplane.yaml
talosctl -e 192.168.0.5 -n 192.168.0.6 apply-config -f worker.yaml
# certs regenerate automatically; no reboot. Then talosctl works over the
# tailnet (and kubectl no longer needs the tls-server-name pin).
```

> Note: `talosctl` is now installed by the playbook (in `group_vars/all.yml`
> `desktop_brews`), and `talosconfig` is fetched from Bitwarden by the `kube` role.
