# Account-level guardrails.

# Every new EBS volume/snapshot copy is encrypted (AWS-managed key). Existing
# volumes are unaffected — re-encrypting them means snapshot → copy → swap.
resource "aws_ebs_encryption_by_default" "eu_north_1" {
  enabled = true
}

resource "aws_ebs_encryption_by_default" "us_east_1" {
  provider = aws.us_east_1
  enabled  = true
}
