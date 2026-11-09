# Bootstrap — run this ONCE, manually, before anything else in infra/.
# Everything downstream uses the S3 bucket + DynamoDB table created here as
# its remote state backend, so this can't itself use that backend (chicken
# and egg) — it uses local state, which is fine since it changes rarely.
#
# Usage:
#   cd infra/bootstrap
#   terraform init
#   terraform apply
#
# After this succeeds, copy the bucket name it outputs into
# environments/dev/backend.hcl before running terraform init anywhere else.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region for the state backend"
  type        = string
  default     = "ap-south-1"
}

variable "project_name" {
  description = "Used as a prefix for the state bucket/table names"
  type        = string
  default     = "chatbot-agent"
}

resource "aws_s3_bucket" "terraform_state" {
  # Bucket names are globally unique — the account ID suffix avoids collisions.
  bucket = "${var.project_name}-tfstate-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "terraform_lock" {
  name         = "${var.project_name}-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }
}

data "aws_caller_identity" "current" {}

output "state_bucket_name" {
  value = aws_s3_bucket.terraform_state.bucket
}

output "lock_table_name" {
  value = aws_dynamodb_table.terraform_lock.name
}
