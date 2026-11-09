variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

# EKS Auto Mode needs a cluster IAM role with these two policies — Auto Mode
# manages node lifecycle itself, so this role is far smaller than a
# traditional self-managed EKS cluster role would need.
resource "aws_iam_role" "cluster" {
  name = "${var.project_name}-eks-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "eks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role_policy_attachment" "compute_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSComputePolicy"
}

resource "aws_iam_role_policy_attachment" "block_storage_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSBlockStoragePolicy"
}

resource "aws_iam_role_policy_attachment" "load_balancing_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSLoadBalancingPolicy"
}

resource "aws_iam_role_policy_attachment" "networking_policy" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSNetworkingPolicy"
}

resource "aws_eks_cluster" "main" {
  name     = var.project_name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids = var.private_subnet_ids
  }

  # Auto Mode: AWS manages node provisioning, patching, and scaling — no
  # separate managed node group resource needed for the general-purpose
  # workloads. The GPU node pool below is where we still express intent
  # (instance types, taints) since Auto Mode's default pools aren't GPU-aware.
  compute_config {
    enabled       = true
    node_pools    = ["general-purpose", "system"]
    node_role_arn = aws_iam_role.node.arn
  }

  kubernetes_network_config {
    elastic_load_balancing {
      enabled = true
    }
  }

  storage_config {
    block_storage {
      enabled = true
    }
  }

  access_config {
    authentication_mode = "API"
  }

  depends_on = [
    aws_iam_role_policy_attachment.cluster_policy,
    aws_iam_role_policy_attachment.compute_policy,
    aws_iam_role_policy_attachment.block_storage_policy,
    aws_iam_role_policy_attachment.load_balancing_policy,
    aws_iam_role_policy_attachment.networking_policy,
  ]
}

# Node role for Auto Mode's managed nodes — separate from the cluster role.
resource "aws_iam_role" "node" {
  name = "${var.project_name}-eks-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "node_auto_node_policy" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "node_ecr_pull" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# OIDC provider — required for Pod Identity Association (Phase 2, step 4).
data "tls_certificate" "eks" {
  url = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "eks" {
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks.certificates[0].sha1_fingerprint]
  url             = aws_eks_cluster.main.identity[0].oidc[0].issuer
}

# Required for Pod Identity Association to function at all — without this
# addon, associating an IAM role with a service account has no effect;
# pods never receive credentials. EKS Auto Mode manages several addons
# itself (networking, storage, load balancing, per compute_config /
# storage_config above), but pod identity is not one of them — it's
# always an explicit addon.
resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name = aws_eks_cluster.main.name
  addon_name   = "eks-pod-identity-agent"

  depends_on = [aws_eks_cluster.main]
}

# GPU node class + pool for LLM serving pods (vLLM/TGI) — Phase 3.
# This is Karpenter-style NodePool/NodeClass config expressed via the EKS
# Auto Mode CRDs; applied via kubectl/GitOps once the cluster exists, not
# as a Terraform resource — Auto Mode's node pools are Kubernetes objects,
# not AWS API resources. See ../../k8s/gpu-nodepool.yaml alongside this.

output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.main.endpoint
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.eks.arn
}

output "cluster_certificate_authority_data" {
  value = aws_eks_cluster.main.certificate_authority[0].data
}

output "node_role_name" {
  value = aws_iam_role.node.name
}
