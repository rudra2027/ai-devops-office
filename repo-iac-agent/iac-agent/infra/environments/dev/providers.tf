# Provider configuration for this environment. Terraform, backend, and all
# three providers (aws, tls, kubernetes) live here — everything else in
# this directory is module wiring and variable declarations only.
#
# CREDENTIALS: this file declares HOW Terraform authenticates to AWS, not
# the actual secret values. Real values go in terraform.tfvars, which is
# gitignored (see infra/.gitignore) — same pattern as .env everywhere else
# in this project. Never put a real access key directly in this file.
#
# Two ways to authenticate, pick one:
#
#   1. (Recommended) AWS CLI profile or environment variables — leave
#      aws_access_key/aws_secret_key as null in terraform.tfvars (or omit
#      them entirely) and either:
#        - run `aws configure` once, and set aws_profile in terraform.tfvars
#          to that profile's name, OR
#        - export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY /
#          AWS_SESSION_TOKEN in your shell before running terraform — the
#          AWS provider picks these up automatically, no Terraform variable
#          needed at all.
#
#   2. Explicit keys in terraform.tfvars — only if neither of the above is
#      an option. Copy terraform.tfvars.example to terraform.tfvars and
#      fill in aws_access_key/aws_secret_key there. This is the least
#      preferred option — a plaintext credential sitting in a file, even a
#      gitignored one, is a real exposure risk (backups, shared machines,
#      accidental `zip -r` of the whole directory). Prefer option 1.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.31"
    }
  }

  # Filled in via `terraform init -backend-config=backend.hcl` — bucket
  # and table names come from bootstrap/'s outputs. See backend.hcl.example.
  backend "s3" {}
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "aws_profile" {
  description = "AWS CLI profile name — leave null to use env vars or the default profile instead"
  type        = string
  default     = null
}

variable "aws_access_key" {
  description = "Only set this in terraform.tfvars if you're not using a profile or env vars — see the file header comment"
  type        = string
  default     = null
  sensitive   = true
}

variable "aws_secret_key" {
  description = "Only set this in terraform.tfvars if you're not using a profile or env vars — see the file header comment"
  type        = string
  default     = null
  sensitive   = true
}

provider "aws" {
  region     = var.aws_region
  profile    = var.aws_profile
  access_key = var.aws_access_key
  secret_key = var.aws_secret_key
}

# The kubernetes provider authenticates against the APPLICATION cluster
# specifically (not the LLM cluster) — this is what lets Terraform create
# the blue/green namespace objects directly, rather than leaving that
# entirely to kubectl/ArgoCD the way the GPU NodePool is handled.
data "aws_eks_cluster_auth" "app" {
  name = module.eks_app.cluster_name
}

provider "kubernetes" {
  host                   = module.eks_app.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks_app.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.app.token
}
