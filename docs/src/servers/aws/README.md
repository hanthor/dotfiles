# TunaOS AWS Account

> **Cluster terminated 2026-10-25; IaC is not reconciled.** The
> [AWS Talos cluster](../aws-k8s/cluster.md) is historical. Matrix and
> standalone LiveKit are deployed on the [OCI spindle VPS](../spindle-vps/README.md).
> S3 backups and a mirror on himachal-1 were retained; do not assume other
> AWS resources have been removed or retained without checking the account.
>
> **Do not blindly run `just aws-plan` or `just aws-apply`.** `aws/` still
> describes removed cluster resources. A plan can propose recreating them;
> applying it can recreate infrastructure and incur costs. Review live state,
> configuration and every proposed action before any apply.

This TunaOS account's OpenTofu configuration is in
[`aws/`](https://github.com/hanthor/dotfiles/tree/master/aws); `runs-on` was
managed separately by CloudFormation. The table describes the configuration
and prior deployment, not a verified live resource inventory.

| Region | Configured or historical resource | Configuration |
|---|---|---|
| `eu-north-1` | Terminated Talos cluster — VPC, nodes, Elastic IPs, security groups, pgdata volume | `aws/cluster.tf` |
| `eu-north-1` | Backup configuration — DLM policy and retained fleet-backups bucket | `aws/backups.tf` |
| `us-east-1` | Punjab EC2 retirement in progress; root volume and five recovery snapshots retained | `aws/punjab.tf` |
| `us-east-2` | `runs-on` stack deleted 2026-10-28; cache/log buckets retained | Former CloudFormation stack `runs-on` |
| global | IAM, backup, account and budget configuration | `aws/iam.tf`, `aws/backups.tf`, `aws/account.tf`, `aws/budgets.tf` |

## Verified retirement inventory (2026-10-28)

An administrator inventory covered all 17 enabled regions. Punjab was the only
remaining EC2 instance; no NAT gateways, load balancers or RDS instances were
found. The `runs-on` Fargate manager and six Lambda functions were retired with
its CloudFormation stack; deletion reached `DELETE_COMPLETE`, with no ECS
clusters or Lambda functions remaining in `us-east-2`.

All three S3 buckets remain. The runner cache and logging buckets retained all
observed object versions; their lifecycle expiration was disabled. Private
runner recovery material is root-only on the replacement under
`/srv/punjab-migration/runs-on-retirement/`. The fleet-backups bucket was not
modified. Both DLM policies are disabled to freeze the recovery snapshot set;
the five completed Punjab snapshots remain. Retained storage still incurs
charges; this is not a zero-bill claim.

## OpenTofu layout

```
aws/
├── versions.tf     # provider (eu-north-1 default, us_east_1 alias) + S3 backend
├── cluster.tf      # VPC/subnet/IGW/routes, 3 SGs, 2 Talos nodes, EIPs, pgdata
├── backups.tf      # DLM role + policy, fleet-backups bucket (+ versioning/SSE/lifecycle)
├── punjab.tf       # retained stopped instance, key pair, SG, SSM role, disabled DLM
├── account.tf      # EBS encryption by default (both regions)
├── iam.tf          # scoped admin user + its policies
├── budgets.tf      # 5 budgets, one for_each
├── imports.tf      # one-time adoption record (no-op once imported)
├── variables.tf
└── terraform.tfvars.example
```

- **State**: in the fleet-backups bucket under `tofu/aws/`
  (versioned, SSE-S3, lockfile). It contains the Talos nodes' `user_data` —
  i.e. cluster PKI — so it never goes in git.
- **Variables**: `aws/terraform.tfvars` holds the alert email and the admin
  ingress allowlists. The repo is public, so it is gitignored and stored in the
  Bitwarden secure note **`aws-tofu-tfvars`**.
- **Talos user_data is not in the config.** The node resources ignore `user_data`
  and `ami`; `prevent_destroy` is configured on the nodes, punjab, worker EIP,
  pgdata volume and backup bucket. It does not prevent creation of resources
  missing from the account.

## Usage and drift

The former expectation of a no-change plan no longer applies after termination.
Do not treat drift as a reason to restore resources. Before using `just aws-plan`,
inspect the account and configuration; review the resulting plan carefully and
reconcile the intended resource lifecycle before any `just aws-apply`. Planning
does not itself create resources, but applying proposed creates can restore
infrastructure and incur charges. `aws/terraform.tfvars` remains sensitive;
`just aws-seed-tfvars` stores it in Bitwarden after an intentional edit.

### Punjab replacement transition (2026-10-28)

The fleet inventory's logical `punjab` host now connects to the replacement
guest on Karnataka at `100.103.187.46`, using the verified `ubuntu` account.
The replacement now owns the Tailscale name **`punjab`**; the old node is
`punjab-aws-retired`. Authenticated SSH, broker access, the native no-secrets
apply and monitoring were exercised on the replacement, including reboot
persistence. Atuin's pre-existing cloud account/key mismatch remains unresolved;
local history and its key were retained.

`aws/punjab.tf` retains the original EC2 instance, volume protection, security
group, key pair and SSM role/profile for recovery. Its desired instance state
is explicitly stopped, the EIP declaration and former cluster allowlist
dependency are removed, and DLM is disabled. It does **not** manage the
replacement guest. The replacement retains AWS administration tools and its
SSH-hardening and no-proxy policies.

The shutdown handoff's root-only receipt on the replacement is
`/srv/punjab-migration/aws-cutover-receipt.json`; it records observed EC2
shutdown and EIP release, rather than treating a config edit as proof.
The former cluster's broader declarations still require separate state/config
reconciliation: deleted resources declared here can be proposed for recreation.
`prevent_destroy` does not protect against recreation. Retain S3 backups,
recovery storage and state; do not use a blanket destroy to resolve that drift.

## IAM & access

- **Root** historically had MFA and no access keys. Verify current access
  configuration before relying on it.
- **A scoped admin user** was the day-to-day identity, with EC2, S3, budgets,
  DLM, SSM and read-only IAM access. The historical key item is `aws-james-admin`;
  verify its current permissions and status before use.
- **A backup user** was configured for put/get under `postgres/` in the backup
  bucket, with no delete. Its key was stored in Bitwarden as `postgres-backup-s3`
  and in the former cluster's `postgres/postgres-backup-s3` Secret, not tofu state.
- **punjab's configured instance role** has `AmazonSSMManagedInstanceCore`.
- DNS was managed on Cloudflare. Verify current AWS security and DNS settings
  before relying on this historical inventory.

## Backups

The S3 fleet-backups bucket was retained, as was a mirror on himachal-1 at
`~/backups/tunaos-aws-2026-10-25`. Protect these backups and the OpenTofu state;
do not assume their presence means every former cluster volume or snapshot
survived. The former cluster uploaded verified Postgres dumps to
`postgres/<date>/`; configured S3 lifecycle rules moved them to IA after 30
days, Glacier IR after 90, and expired them after a year. Check live bucket
settings before relying on that schedule.

The configuration also describes DLM schedules for the former Talos root
volumes and punjab. Those schedules and the availability of individual snapshots
are not a current backup inventory.

## Cost

The AWS credits were exhausted. Remaining resources can incur charges, and
recreating cluster infrastructure would add costs. `aws/budgets.tf` describes
budget alerts; verify current budgets and actual charges in the AWS account.
