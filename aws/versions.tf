terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # State lives next to the Postgres dumps: private, versioned, SSE-S3. It
  # holds the Talos nodes' user_data (cluster PKI), so it must never be
  # committed — see .gitignore.
  backend "s3" {
    bucket       = "hanthor-fleet-backups-181185361136"
    key          = "tofu/aws/terraform.tfstate"
    region       = "eu-north-1"
    encrypt      = true
    use_lockfile = true
  }
}

# The Talos cluster, backups and DLM live in eu-north-1.
provider "aws" {
  region = "eu-north-1"
}

# punjab (this repo's AWS-hosted fleet member) lives in us-east-1.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}
