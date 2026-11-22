# One-time adoption of resources that were created by hand (2026-07 → 09).
# Once imported these blocks are no-ops; they stay as a record of what was
# adopted. The terminated Talos cluster's imports were dropped when it was
# forgotten (removed.tf).
# (Import IDs can't use data sources, hence the literal account ID below.)

# punjab
import {
  provider = aws.us_east_1
  to       = aws_instance.punjab
  id       = "i-085690e02ca98c95a"
}
import {
  provider = aws.us_east_1
  to       = aws_security_group.punjab_ssh
  id       = "sg-0670c5a3a5e2115e9"
}
import {
  provider = aws.us_east_1
  to       = aws_key_pair.punjab
  id       = "punjab"
}
import {
  to = aws_dlm_lifecycle_policy.fleet_daily
  id = "policy-0f074c7d13f94e355"
}
import {
  to = aws_s3_bucket.fleet_backups
  id = "hanthor-fleet-backups-181185361136"
}
import {
  to = aws_s3_bucket_versioning.fleet_backups
  id = "hanthor-fleet-backups-181185361136"
}
import {
  to = aws_s3_bucket_lifecycle_configuration.fleet_backups
  id = "hanthor-fleet-backups-181185361136"
}
import {
  to = aws_s3_bucket_public_access_block.fleet_backups
  id = "hanthor-fleet-backups-181185361136"
}
import {
  to = aws_s3_bucket_server_side_encryption_configuration.fleet_backups
  id = "hanthor-fleet-backups-181185361136"
}
# IAM
import {
  to = aws_iam_user.james_admin
  id = "james-admin"
}
import {
  to = aws_iam_policy.james_admin_migration_scope
  id = "arn:aws:iam::181185361136:policy/james-admin-migration-scope"
}
import {
  to = aws_iam_user_policy_attachment.james_admin_migration_scope
  id = "james-admin/arn:aws:iam::181185361136:policy/james-admin-migration-scope"
}
import {
  to = aws_iam_user_policy.james_admin_dlm
  id = "james-admin:james-admin-dlm"
}
import {
  to = aws_iam_role.dlm
  id = "AWSDataLifecycleManagerDefaultRole"
}
import {
  to = aws_iam_role_policy_attachment.dlm
  id = "AWSDataLifecycleManagerDefaultRole/arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}
# budgets
import {
  to = aws_budgets_budget.this["migration"]
  id = "181185361136:migration-monthly-spend"
}
import {
  to = aws_budgets_budget.this["bedrock"]
  id = "181185361136:bedrock-monthly-spend"
}
import {
  to = aws_budgets_budget.this["kiro"]
  id = "181185361136:kiro-monthly-spend"
}
import {
  to = aws_budgets_budget.this["credits_exhausted"]
  id = "181185361136:credits-exhausted-alarm"
}
import {
  to = aws_budgets_budget.this["account_total"]
  id = "181185361136:tuna-os-account-total"
}
