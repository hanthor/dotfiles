# Punjab

Punjab is the headless agent/dev VM on Karnataka. Matrix and the Hives run
separately on the [OCI spindle VPS](../spindle-vps/README.md).

## Active replacement

- KubeVirt VM: `corral-vms/punjab`, on Karnataka's local-path storage.
- Ubuntu 24.04, 4 vCPUs, 12 GiB RAM, 320 GiB virtual root disk.
- Tailscale: **punjab**, `100.103.187.46`; SSH user **ubuntu**.
- Connect with `ssh ubuntu@punjab` or `ssh ubuntu@100.103.187.46`.
- `/etc/dotfiles-machine` is `punjab`. The guest keeps its own SSH host keys,
  machine ID and Tailscale identity; none were copied from EC2.
- The old EC2 tailnet node is named `punjab-aws-retired`.

The manifest is [`vm-migrations/punjab.yaml`](https://github.com/hanthor/dotfiles/blob/master/vm-migrations/punjab.yaml).
Its cloud-init network data uses DHCPv4 only. The masquerade interface's MTU
is below IPv6's minimum; requesting DHCPv6 caused a network-online timeout
on reboot. Full VM startup and a subsequent in-guest reboot were exercised;
authenticated SSH, broker access and the enabled services returned afterward.

Karnataka and its local disk are now a dependency of this host. This is not
HA storage; losing Karnataka or that disk requires recovery from backups.

## Configuration and services

The canonical checkout is `~/.local/share/dotfiles`, deployed from
`feat/native-laptop-units` while [PR #348](https://github.com/hanthor/dotfiles/pull/348)
is under review. Native Bash units run through mise; no Ansible apply is used
by the replacement's update service. The user timer and Atuin daemon use
linger so they can run without an SSH login.
The real `just apply-nosecrets` completed successfully on the replacement;
secret-dependent setup reports partial/skipped rather than pretending to run.

- omp authenticates through the Spindle broker at `http://100.113.75.88:8765`.
  The obsolete shell override pointing at EC2 was removed by chezmoi adoption.
- Atuin's local history and key were copied and their history database matched
  the source at cutover. Cloud sync was already logged out; the local key
  differs from the Bitwarden item. Neither key nor history was overwritten.
  Resolve that account/key mismatch before attempting cloud sync.
- osquery's daemon, local report timer and fleet poll timer run on the VM.
  The temporary staging-hostname baseline is retained privately; a new baseline
  was accepted for the final `punjab` identity. Missing reporters on the reachable
  Karnataka and Himachal nodes were provisioned during validation.
- SSH password/root login is disabled by the native sshd hardening configuration.
- `skip_proxy: true` remains set; the VM is not a desktop.

**Kiro Crew is retired.** Its service is disabled/masked, the launcher and
fleet integration are removed, and its private recovery data is quarantined.
Kiro CLI and omp integrations are separate and remain available.

## Preserved migration data

`/srv/punjab-migration/` is root-only and contains:

- `source-system/`: the EC2 system-state recovery copy, not a replacement for
  the VM's live networking, machine identity or system directories.
- `guest-original-home/`: the pre-cutover guest home.
- `kirocrew-retired/`: quarantined application data/runtime files.
- `terminal-recovery.tgz`: five tmux panes' scrollback, working-directory
  inventory and the former user crontab. Existing processes cannot move live.
- `runs-on-retirement/`: private runner stack/configuration/secret recovery
  material and retention evidence. Never publish these files.

The old home copy is now `/home/ubuntu`; Homebrew is `/home/linuxbrew`.
The old source checkout, including its branch and uncommitted work, is retained
at `~/.local/share/dotfiles-ec2-recovery`. Its four modified tracked files were
also copied into the active checkout. Other old temporary worktrees remain
in the system recovery copy; their original absolute Git paths may need repair
before reuse.

## AWS recovery and shutdown handoff

The former EC2 instance is `i-085690e02ca98c95a` in `us-east-1`. Its intended
recovery state is **stopped**, not terminated. The 250 GiB root volume
`vol-09fdb248c28e850ca` and five completed snapshots are retained. Snapshot
`snap-0bc709516bb003e9a` was taken while EC2 was live: it is crash-consistent,
not proof of an application-consistent restore.

The shutdown runs from the replacement after its checks, not from a process
that needs EC2 to stay online. The root-only receipt at
`/srv/punjab-migration/aws-cutover-receipt.json` records the observed EC2 and
EIP retirement result; consult it and AWS rather than assuming completion
from a documentation entry. The EIP allocation to release is
`eipalloc-00f40f76478a3ea02`.

The `runs-on` stack reached `DELETE_COMPLETE`; its two S3 buckets and all
observed versions were retained. The fleet-backups S3 bucket remains intact.
Both DLM policies are disabled. Storage still incurs charges. The former
cluster's broader IaC remains historical: follow the warnings in the
[AWS handbook](../aws/README.md), not a blanket `tofu apply` or `destroy`.
