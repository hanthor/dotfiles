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
| `us-east-1` | [punjab](../punjab/README.md) EC2 agent box; running as of 2026-10-27 | `aws/punjab.tf` |
| `us-east-2` | `runs-on` GitHub Actions runners; current stack status unverified | CloudFormation stack `runs-on` |
| global | IAM, backup, account and budget configuration | `aws/iam.tf`, `aws/backups.tf`, `aws/account.tf`, `aws/budgets.tf` |

## OpenTofu layout

```
aws/
├── versions.tf     # provider (eu-north-1 default, us_east_1 alias) + S3 backend
├── cluster.tf      # VPC/subnet/IGW/routes, 3 SGs, 2 Talos nodes, EIPs, pgdata
├── backups.tf      # DLM role + policy, fleet-backups bucket (+ versioning/SSE/lifecycle)
├── punjab.tf       # key pair, SG, instance, EIP, SSM role, DLM
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
