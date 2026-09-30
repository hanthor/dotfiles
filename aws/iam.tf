# james-admin: the scoped IAM user used day-to-day instead of root.
# Its access key lives in Bitwarden, never here.

resource "aws_iam_user" "james_admin" {
  name = "james-admin"
}

resource "aws_iam_policy" "james_admin_migration_scope" {
  name = "james-admin-migration-scope"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "Compute", Effect = "Allow", Action = ["ec2:*"], Resource = "*" },
      { Sid = "StorageBackups", Effect = "Allow", Action = ["s3:*"], Resource = "*" },
      { Sid = "CostControl", Effect = "Allow", Action = ["budgets:*", "ce:Get*", "ce:Describe*"], Resource = "*" },
      {
        Sid       = "PassRoleToEC2"
        Effect    = "Allow"
        Action    = ["iam:PassRole"]
        Resource  = "*"
        Condition = { StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" } }
      },
      { Sid = "SelfIdentity", Effect = "Allow", Action = ["sts:GetCallerIdentity", "iam:GetUser", "iam:ListAccessKeys"], Resource = "*" },
      # Read-only IAM so `just aws-plan` works as james-admin; IAM *changes*
      # still need root.
      { Sid = "IamRead", Effect = "Allow", Action = ["iam:Get*", "iam:List*"], Resource = "*" },
      # Session Manager break-glass into punjab.
      { Sid = "SsmSessions", Effect = "Allow", Action = ["ssm:StartSession", "ssm:TerminateSession", "ssm:ResumeSession", "ssm:DescribeSessions", "ssm:DescribeInstanceInformation", "ssm:GetConnectionStatus"], Resource = "*" },
    ]
  })
}

resource "aws_iam_user_policy_attachment" "james_admin_migration_scope" {
  user       = aws_iam_user.james_admin.name
  policy_arn = aws_iam_policy.james_admin_migration_scope.arn
}

resource "aws_iam_user_policy" "james_admin_dlm" {
  name = "james-admin-dlm"
  user = aws_iam_user.james_admin.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "ManageSnapshotLifecycle", Effect = "Allow", Action = "dlm:*", Resource = "*" },
      {
        Sid       = "PassOnlyTheDlmRole"
        Effect    = "Allow"
        Action    = "iam:PassRole"
        Resource  = aws_iam_role.dlm.arn
        Condition = { StringEquals = { "iam:PassedToService" = "dlm.amazonaws.com" } }
      },
    ]
  })
}
