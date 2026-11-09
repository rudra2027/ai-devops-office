# Provider/backend config lives in providers.tf — this file is module
# wiring and variables only.

variable "project_name" {
  type    = string
  default = "chatbot-agent"
}

variable "azs" {
  type    = list(string)
  default = ["ap-south-1a", "ap-south-1b"]
}

variable "frontend_image" {
  description = "ECR image URI for the frontend — placeholder until Phase 3/7 push a real one"
  type        = string
  default     = "public.ecr.aws/nginx/nginx:latest"
}

module "vpc" {
  source        = "../../modules/vpc"
  project_name  = var.project_name
  azs           = var.azs
  cluster_names = [local.llm_cluster_name, local.app_cluster_name]
}

locals {
  llm_cluster_name = "${var.project_name}-llm"
  app_cluster_name = "${var.project_name}-app"
}

# --- Two clusters: LLM serving is isolated from the application ---
# Separate blast radius, separate scaling profile (GPU vs CPU), and no
# need for node taints to keep GPU-hungry LLM pods off the app cluster's
# general-purpose nodes. Both share the same VPC (cost — no second NAT
# gateway needed).

module "eks_llm" {
  source             = "../../modules/eks"
  project_name       = local.llm_cluster_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
}

module "eks_app" {
  source             = "../../modules/eks"
  project_name       = local.app_cluster_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
}

module "data_services" {
  source             = "../../modules/data-services"
  project_name       = var.project_name
  vpc_id             = module.vpc.vpc_id
  private_subnet_ids = module.vpc.private_subnet_ids
}

module "ecs_frontend" {
  source             = "../../modules/ecs-frontend"
  project_name       = var.project_name
  vpc_id             = module.vpc.vpc_id
  public_subnet_ids  = module.vpc.public_subnet_ids
  private_subnet_ids = module.vpc.private_subnet_ids
  frontend_image     = var.frontend_image
  # Backend Ingress URL isn't known until the app cluster's Ingress
  # controller is deployed — placeholder until Phase 6.
  backend_url        = "https://backend.placeholder.internal"
}

module "cdn" {
  source       = "../../modules/cdn"
  project_name = var.project_name
  alb_dns_name = module.ecs_frontend.alb_dns_name
}

output "llm_cluster_name" {
  value = module.eks_llm.cluster_name
}

output "llm_cluster_endpoint" {
  value = module.eks_llm.cluster_endpoint
}

output "llm_cluster_node_role_name" {
  value = module.eks_llm.node_role_name
}

output "app_cluster_name" {
  value = module.eks_app.cluster_name
}

output "app_cluster_endpoint" {
  value = module.eks_app.cluster_endpoint
}

output "frontend_alb_dns_name" {
  value = module.ecs_frontend.alb_dns_name
}

output "cloudfront_domain_name" {
  value = module.cdn.distribution_domain_name
}

output "efs_file_system_id" {
  value = module.data_services.efs_file_system_id
}

output "iac_findings_table_name" {
  value = module.data_services.iac_findings_table_name
}
