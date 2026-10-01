# aws/ — AWS account IaC (OpenTofu)

Codifies everything in the AWS account except the `runs-on` CloudFormation
stack: the eu-north-1 Talos cluster's infrastructure, punjab, backups, IAM
and budgets.

```bash
just aws-plan    # should always say "No changes"
just aws-apply
```

Full handbook: [docs/src/servers/aws/README.md](../docs/src/servers/aws/README.md).
State is in S3 and `terraform.tfvars` is in Bitwarden (`aws-tofu-tfvars`).
Neither is in git.
