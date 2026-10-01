# One-time adoption of resources that were created by hand (2026-07 → 09).
# Once imported these blocks are no-ops; they stay as a record of what was
# adopted and so a fresh state can be rebuilt with `tofu apply`.
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
# cluster network
import {
  to = aws_vpc.migration
  id = "vpc-0c8fdba0b442b9af1"
}
import {
  to = aws_subnet.public_a
  id = "subnet-0213792ff023a3737"
}
import {
  to = aws_internet_gateway.migration
  id = "igw-0e2ffcdc182f80672"
}
import {
  to = aws_route_table.public
  id = "rtb-02a8a143552755b18"
}
import {
  to = aws_route_table_association.public_a
  id = "subnet-0213792ff023a3737/rtb-02a8a143552755b18"
}
import {
  to = aws_security_group.intracluster
  id = "sg-0421d172cf0a202d8"
}
import {
  to = aws_security_group.matrix_public
  id = "sg-09803bdbcc7b9273a"
}
import {
  to = aws_security_group.admin_bootstrap
  id = "sg-052a6292d2dcf728e"
}
import {
  to = aws_instance.controlplane
  id = "i-00a3e4532cdbfc87e"
}
import {
  to = aws_instance.worker
  id = "i-0bdfafdebc799d49d"
}
import {
  to = aws_eip.controlplane
  id = "eipalloc-0d1d4a449bb5eb751"
}
import {
  to = aws_eip.worker
  id = "eipalloc-0c8535b0d86005345"
}
import {
  to = aws_ebs_volume.pgdata
  id = "vol-01ff00a316340f0ad"
}
import {
  to = aws_volume_attachment.pgdata
  id = "/dev/xvdb:vol-01ff00a316340f0ad:i-0bdfafdebc799d49d"
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
