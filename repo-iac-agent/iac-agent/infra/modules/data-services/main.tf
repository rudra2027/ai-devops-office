variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

# --- EFS for shared model weights (Phase 2, step 6) ---

resource "aws_security_group" "efs" {
  name_prefix = "${var.project_name}-efs-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = [data.aws_vpc.selected.cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

data "aws_vpc" "selected" {
  id = var.vpc_id
}

resource "aws_efs_file_system" "model_weights" {
  creation_token = "${var.project_name}-model-weights"
  encrypted      = true

  tags = {
    Name = "${var.project_name}-model-weights"
  }
}

resource "aws_efs_mount_target" "model_weights" {
  count           = length(var.private_subnet_ids)
  file_system_id  = aws_efs_file_system.model_weights.id
  subnet_id       = var.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs.id]
}

# --- Secrets Manager (Phase 2, step 5) ---
# Secrets themselves are seeded manually/via CI, never with real values in
# Terraform state — these resources just create the named slots.

resource "aws_secretsmanager_secret" "omni_route_api_key" {
  name = "${var.project_name}/omni-route-api-key"
}

resource "aws_secretsmanager_secret" "langsmith_api_key" {
  name = "${var.project_name}/langsmith-api-key"
}

# --- S3 for model artifacts (Phase 2, step 7 — separate from the tfstate
# bucket created in bootstrap/) ---

resource "aws_s3_bucket" "model_artifacts" {
  bucket = "${var.project_name}-model-artifacts-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "model_artifacts" {
  bucket                  = aws_s3_bucket.model_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- Findings table for the IaC agent (Phase 10) + audit log ---
# DynamoDB chosen over RDS per the build guide's "open decisions" — no
# schema migrations to manage for a single-table access pattern like this.

resource "aws_dynamodb_table" "iac_findings" {
  name         = "${var.project_name}-iac-findings"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  # Lets the agent and the dashboard both query "give me all pending
  # findings" without a table scan.
  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    projection_type = "ALL"
  }
}

# --- SQS for agent<->router decoupling (Phase 2, step 8) ---

resource "aws_sqs_queue" "agent_tasks" {
  name                       = "${var.project_name}-agent-tasks"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 86400

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.agent_tasks_dlq.arn
    maxReceiveCount      = 3
  })
}

resource "aws_sqs_queue" "agent_tasks_dlq" {
  name                      = "${var.project_name}-agent-tasks-dlq"
  message_retention_seconds = 1209600 # 14 days — max, for post-mortem room
}

data "aws_caller_identity" "current" {}

output "efs_file_system_id" {
  value = aws_efs_file_system.model_weights.id
}

output "omni_route_secret_arn" {
  value = aws_secretsmanager_secret.omni_route_api_key.arn
}

output "langsmith_secret_arn" {
  value = aws_secretsmanager_secret.langsmith_api_key.arn
}

output "model_artifacts_bucket" {
  value = aws_s3_bucket.model_artifacts.bucket
}

output "iac_findings_table_name" {
  value = aws_dynamodb_table.iac_findings.name
}

output "agent_tasks_queue_url" {
  value = aws_sqs_queue.agent_tasks.url
}

output "agent_tasks_queue_arn" {
  value = aws_sqs_queue.agent_tasks.arn
}

output "iac_findings_table_arn" {
  value = aws_dynamodb_table.iac_findings.arn
}
