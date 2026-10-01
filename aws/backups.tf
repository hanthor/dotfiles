# Off-node backups: nightly EBS snapshots of both nodes' root volumes (DLM),
# plus an S3 bucket for Postgres dumps and this config's tofu state.

resource "aws_iam_role" "dlm" {
  name = "AWSDataLifecycleManagerDefaultRole"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "dlm.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

# Targets every volume tagged Backup=fleet-daily (both root volumes).
# 03:30 UTC daily ×7, 03:45 UTC Sunday ×4.
resource "aws_dlm_lifecycle_policy" "fleet_daily" {
  description        = "Fleet node root volumes daily and weekly snapshots"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags = {
      Backup = "fleet-daily"
    }

    schedule {
      name        = "daily-7d"
      copy_tags   = true
      tags_to_add = { dlm-schedule = "daily-7d" }
      create_rule {
        cron_expression = "cron(30 3 * * ? *)"
      }
      retain_rule {
        count = 7
      }
    }

    schedule {
      name        = "weekly-4w"
      copy_tags   = true
      tags_to_add = { dlm-schedule = "weekly-4w" }
      create_rule {
        cron_expression = "cron(45 3 ? * SUN *)"
      }
      retain_rule {
        count = 4
      }
    }
  }
}

resource "aws_s3_bucket" "fleet_backups" {
  bucket = "hanthor-fleet-backups-${data.aws_caller_identity.current.account_id}"
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "fleet_backups" {
  bucket = aws_s3_bucket.fleet_backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "fleet_backups" {
  bucket = aws_s3_bucket.fleet_backups.id
  rule {
    bucket_key_enabled = true
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "fleet_backups" {
  bucket                  = aws_s3_bucket.fleet_backups.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# postgres/ dumps: IA at 30d, Glacier IR at 90d, gone at 1y. Everything else
# (incl. tofu/ state) is kept; only stale multipart uploads are cleaned.
resource "aws_s3_bucket_lifecycle_configuration" "fleet_backups" {
  bucket = aws_s3_bucket.fleet_backups.id

  rule {
    id     = "tier-and-expire"
    status = "Enabled"
    filter {
      prefix = "postgres/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }

  rule {
    id     = "abort-incomplete"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Writer for the in-cluster Postgres dump job (talos-k8s/backup/). Put + Get
# (for size verification) under postgres/ only — no delete, so with versioning
# a leaked key can't destroy existing dumps. Its access key is created out of
# band (never in state) and lives in the k8s Secret postgres/postgres-backup-s3
# and the Bitwarden note `postgres-backup-s3`.
resource "aws_iam_user" "postgres_backup" {
  name = "postgres-backup-writer"
}

resource "aws_iam_user_policy" "postgres_backup" {
  name = "fleet-backups-postgres-write"
  user = aws_iam_user.postgres_backup.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "PostgresDumps"
      Effect   = "Allow"
      Action   = ["s3:PutObject", "s3:GetObject"]
      Resource = "${aws_s3_bucket.fleet_backups.arn}/postgres/*"
    }]
  })
}
