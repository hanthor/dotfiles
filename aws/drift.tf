# Read-only identity for the weekly drift check
# (.github/workflows/tofu-drift.yml). GitHub Actions exchanges its OIDC token
# for this role — no long-lived key anywhere. Only scheduled/manual runs on
# master of hanthor/dotfiles can assume it (not PRs, not forks, not branches).
#
# The job runs `tofu plan -lock=false`, so it needs read on the account and
# on the state object, and no write anywhere. james-admin only has read-only
# IAM, so applying this needs root (or another IAM-capable identity).
# After applying, set the repo variable AWS_DRIFT_ROLE_ARN to
# `tofu output -raw drift_role_arn`.

locals {
  github_repo = "hanthor/dotfiles"
  state_key   = "tofu/aws/terraform.tfstate"
}

# If the account already has a GitHub OIDC provider, import it instead:
#   tofu import aws_iam_openid_connect_provider.github \
#     arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "tofu_drift" {
  name                 = "github-tofu-drift-readonly"
  description          = "Read-only tofu plan from ${local.github_repo} master (tofu-drift.yml)"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRoleWithWebIdentity"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/heads/master"
        }
      }
    }]
  })
}

# Refreshing every managed resource needs broad Describe/Get/List, which is
# what ReadOnlyAccess is for.
resource "aws_iam_role_policy_attachment" "tofu_drift_readonly" {
  role       = aws_iam_role.tofu_drift.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ReadOnlyAccess also grants s3:GetObject on every bucket. Deny object reads
# everywhere except the state object itself, so the role can't fetch the
# Postgres dumps (or anything else) — reading the state is unavoidable.
resource "aws_iam_role_policy" "tofu_drift_limit_objects" {
  name = "deny-object-reads-except-state"
  role = aws_iam_role.tofu_drift.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid         = "OnlyTheStateObject"
        Effect      = "Deny"
        Action      = ["s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectAttributes", "s3:GetObjectTorrent"]
        NotResource = ["${aws_s3_bucket.fleet_backups.arn}/${local.state_key}"]
      },
      {
        Sid      = "NoSecretValues"
        Effect   = "Deny"
        Action   = ["secretsmanager:GetSecretValue", "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "*"
      },
    ]
  })
}

output "drift_role_arn" {
  description = "Set as the GitHub repo variable AWS_DRIFT_ROLE_ARN."
  value       = aws_iam_role.tofu_drift.arn
}
