# TunaOS AWS Account

> **Cluster terminated 2026-10-25; IaC is not reconciled.** The
> [AWS Talos cluster](../aws-k8s/cluster.md) is historical. Matrix and
> standalone LiveKit are deployed on the [OCI spindle VPS](../spindle-vps/README.md).
> S3 backups and a mirror on himachal-1 were retained; do not assume other
> AWS resources have been removed or retained without checking the account.
>
> **Do not blindly run `just aws-apply`.** The cluster's resources are now
> `removed` blocks (`aws/removed.tf`): an apply makes OpenTofu forget them
> without destroying anything. Until that apply has been reviewed and run, a
> plan still lists them. Review live state, configuration and every proposed
> action before any apply.

This TunaOS account's OpenTofu configuration is in
[`aws/`](https://github.com/hanthor/dotfiles/tree/master/aws); `runs-on` was
managed separately by CloudFormation. The table describes the configuration
and prior deployment, not a verified live resource inventory.

| Region | Configured or historical resource | Configuration |
|---|---|---|
| `eu-north-1` | Terminated Talos cluster — VPC, nodes, Elastic IPs, security groups, pgdata volume, KubeVirt node | forgotten via `aws/removed.tf` (unmanaged) |
| `eu-north-1` | Backup configuration — DLM policy and retained fleet-backups bucket | `aws/backups.tf` |
| `us-east-1` | [punjab](../punjab/README.md) EC2 agent box; running as of 2026-10-27 | `aws/punjab.tf` |
| `us-east-2` | `runs-on` GitHub Actions runners; current stack status unverified | CloudFormation stack `runs-on` |
| global | IAM, backup, account and budget configuration | `aws/iam.tf`, `aws/backups.tf`, `aws/account.tf`, `aws/budgets.tf` |
| global | GitHub OIDC provider + read-only drift role | `aws/drift.tf` |

## OpenTofu layout

```
aws/
├── versions.tf     # provider (eu-north-1 default, us_east_1 alias) + S3 backend
├── removed.tf      # forget the terminated Talos cluster (destroy = false)
├── drift.tf        # GitHub OIDC provider + read-only role for tofu-drift.yml
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
  (versioned, SSE-S3, lockfile). It contains (or, in older versions, contained)
  the Talos nodes' `user_data` — i.e. cluster PKI — so it never goes in git.
- **Variables**: `aws/terraform.tfvars` holds the alert email and the admin
  ingress allowlists. The repo is public, so it is gitignored and stored in the
  Bitwarden secure note **`aws-tofu-tfvars`**.
- **Talos user_data is not in the config.** `prevent_destroy` is configured on
  punjab and the backup bucket. It does not prevent creation of resources
  missing from the account.

## Usage and drift

Do not treat drift as a reason to restore resources. Before using `just aws-plan`,
inspect the account and configuration; review the resulting plan carefully and
reconcile the intended resource lifecycle before any `just aws-apply`. Planning
does not itself create resources, but applying proposed creates can restore
infrastructure and incur charges. `aws/terraform.tfvars` remains sensitive;
`just aws-seed-tfvars` stores it in Bitwarden after an intentional edit.

### Forgotten cluster resources

`aws/removed.tf` holds a `removed { lifecycle { destroy = false } }` block for
each resource of the terminated cluster: the `controlplane`, `worker` and
`kubevirt` instances, the `controlplane` and `worker` EIPs, the `pgdata` volume
and its attachment, the `migration` VPC, IGW, `public_a` subnet, route table
and association, the `intracluster`, `matrix_public` and `admin_bootstrap`
security groups, and the KubeVirt kill switch (`budget-action-stop-kubevirt`
role and policy, the `stop_kubevirt` budget action) and power user
(`kubevirt-node-power` and its policy). The next reviewed apply drops them from
state without touching the account.

After that they are **unmanaged**. Anything still live — an unattached EIP, the
pgdata volume, the VPC, the `kubevirt-node-power` user and its hand-made access
key — keeps costing money or access until it is deleted by hand. Check the
account before deciding; nothing here deletes it.

punjab's retired EC2 instance (`aws/punjab.tf`) stays managed: its data is
preserved until an explicit cleanup decision.

### Weekly drift check

`.github/workflows/tofu-drift.yml` runs `tofu plan -detailed-exitcode
-lock=false` every Monday as the read-only `github-tofu-drift-readonly` role
(`aws/drift.tf`), assumed through GitHub OIDC from `master` only. On drift it
opens or comments on the issue "OpenTofu drift detected in aws/" with each
change's action and resource address only. Plan output, which can carry
sensitive values, never reaches the log or an artifact. It closes the issue
when a later plan is clean. The role has `ReadOnlyAccess` but cannot read S3
objects other than the state, or secret values.

The job skips until it is set up:

1. Apply `aws/drift.tf` with IAM-capable credentials (root; james-admin's IAM
   access is read-only), for example
   `tofu apply -target=aws_iam_role_policy.tofu_drift_limit_objects -target=aws_iam_role_policy_attachment.tofu_drift_readonly`.
   If the account already has a GitHub OIDC provider, import it first (see the
   comment in `drift.tf`).
2. Set the repo variable `AWS_DRIFT_ROLE_ARN` to `tofu output -raw drift_role_arn`.
3. Set the repo secret `AWS_TOFU_TFVARS` to the contents of the Bitwarden note
   `aws-tofu-tfvars`. Without the real values every plan would report false drift.

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
`postgres/<date>/`. The configured lifecycle moves them to IA after 30 days and
Glacier IR after 90, and expires nothing, neither current nor noncurrent
versions, until an explicit cleanup decision. Earlier configuration expired
dumps after a year and noncurrent versions after 30 days; until the new rule is
applied, the live bucket may still do so. Check the live bucket settings.

The configuration also describes DLM schedules for the former Talos root
volumes and punjab. Those schedules and the availability of individual snapshots
are not a current backup inventory.

## Cost

The AWS credits were exhausted. Remaining resources can incur charges, and
recreating cluster infrastructure would add costs. `aws/budgets.tf` describes
budget alerts; verify current budgets and actual charges in the AWS account.
