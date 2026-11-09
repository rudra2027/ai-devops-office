# Pod Identity Associations — ties an IAM role to a specific Kubernetes
# service account (namespace + name). Service accounts themselves are
# Kubernetes objects, created via kubectl/Helm/ArgoCD once workloads are
# deployed (Phase 3/6) — this file only creates the IAM side, the
# association, and (for the app cluster) the blue/green namespaces those
# service accounts will live in.
#
# Trust policy is the same shape for every Pod Identity role — EKS's pod
# identity agent (the addon added in modules/eks) is what assumes it on
# the pod's behalf, not the pod directly and not OIDC federation.

data "aws_iam_policy_document" "pod_identity_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

# --- Blue/green namespaces on the APPLICATION cluster only ---
# The LLM cluster doesn't need this split — model serving doesn't carry
# the same deploy-safety requirement the agent/backend does, and keeping
# it single-environment keeps the LLM cluster simpler. This is what
# Argo Rollouts (Phase 8) targets once it's installed.

resource "kubernetes_namespace" "app_blue" {
  metadata {
    name = "blue"
    labels = {
      environment = "blue"
    }
  }
}

resource "kubernetes_namespace" "app_green" {
  metadata {
    name = "green"
    labels = {
      environment = "green"
    }
  }
}

# --- Chatbot backend (app cluster, both blue and green) ---
# Same IAM role for both — permissions don't differ by environment, only
# the workload version running does. Two associations, one role.

resource "aws_iam_role" "chatbot_backend" {
  name               = "${var.project_name}-chatbot-backend"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

data "aws_iam_policy_document" "chatbot_backend" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      module.data_services.omni_route_secret_arn,
      module.data_services.langsmith_secret_arn,
    ]
  }
  statement {
    effect    = "Allow"
    actions   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [module.data_services.agent_tasks_queue_arn]
  }
}

resource "aws_iam_role_policy" "chatbot_backend" {
  name   = "${var.project_name}-chatbot-backend"
  role   = aws_iam_role.chatbot_backend.id
  policy = data.aws_iam_policy_document.chatbot_backend.json
}

resource "aws_eks_pod_identity_association" "chatbot_backend_blue" {
  cluster_name    = module.eks_app.cluster_name
  namespace       = kubernetes_namespace.app_blue.metadata[0].name
  service_account = "chatbot-backend"
  role_arn        = aws_iam_role.chatbot_backend.arn

  depends_on = [module.eks_app]
}

resource "aws_eks_pod_identity_association" "chatbot_backend_green" {
  cluster_name    = module.eks_app.cluster_name
  namespace       = kubernetes_namespace.app_green.metadata[0].name
  service_account = "chatbot-backend"
  role_arn        = aws_iam_role.chatbot_backend.arn

  depends_on = [module.eks_app]
}

# --- IaC agent (app cluster — not blue/green, it's infra tooling, not
# the thing being blue/green deployed itself; one instance is enough) ---
# Intentionally broader permissions than the other roles here — its whole
# job is running `terraform apply` against everything this project
# creates. Revisit with resource-level conditions/tags once running for
# real; reasonable starting point for a learning project, not a hardened
# production policy.

resource "aws_iam_role" "iac_agent" {
  name               = "${var.project_name}-iac-agent"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

data "aws_iam_policy_document" "iac_agent" {
  statement {
    effect    = "Allow"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [
      module.data_services.iac_findings_table_arn,
      "${module.data_services.iac_findings_table_arn}/index/*",
    ]
  }
  statement {
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "ec2:CreateTags",
      "elasticloadbalancing:Describe*",
      "ecs:Describe*",
      "ecs:UpdateService",
      "eks:Describe*",
      "s3:GetObject", "s3:PutObject", "s3:ListBucket",
      "secretsmanager:DescribeSecret",
      "sqs:GetQueueAttributes",
      "dynamodb:DescribeTable",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "iac_agent" {
  name   = "${var.project_name}-iac-agent"
  role   = aws_iam_role.iac_agent.id
  policy = data.aws_iam_policy_document.iac_agent.json
}

resource "aws_eks_pod_identity_association" "iac_agent" {
  cluster_name    = module.eks_app.cluster_name
  namespace       = "default"
  service_account = "iac-agent"
  role_arn        = aws_iam_role.iac_agent.arn

  depends_on = [module.eks_app]
}

# --- AWS Load Balancer Controller (app cluster) — creates/manages the
# backend Ingress ALB dynamically once Ingress resources exist (Phase 6).
# Terraform doesn't create that ALB directly; this is what does, at
# apply-time inside the cluster. ---

resource "aws_iam_role" "lb_controller" {
  name               = "${var.project_name}-lb-controller"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

data "aws_iam_policy_document" "lb_controller" {
  # Representative subset of the official AWS Load Balancer Controller
  # IAM policy — cross-check against the authoritative JSON in the
  # kubernetes-sigs/aws-load-balancer-controller repo before relying on
  # this for a real deployment; that policy is maintained upstream and
  # can gain new required actions between controller versions.
  statement {
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "elasticloadbalancing:Describe*",
      "elasticloadbalancing:Create*",
      "elasticloadbalancing:Delete*",
      "elasticloadbalancing:Modify*",
      "elasticloadbalancing:AddTags",
      "elasticloadbalancing:RemoveTags",
      "elasticloadbalancing:RegisterTargets",
      "elasticloadbalancing:DeregisterTargets",
      "acm:DescribeCertificate",
      "acm:ListCertificates",
      "iam:CreateServiceLinkedRole",
      "shield:GetSubscriptionState",
      "waf-regional:GetWebACL",
      "wafv2:GetWebACL",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "lb_controller" {
  name   = "${var.project_name}-lb-controller"
  role   = aws_iam_role.lb_controller.id
  policy = data.aws_iam_policy_document.lb_controller.json
}

resource "aws_eks_pod_identity_association" "lb_controller" {
  cluster_name    = module.eks_app.cluster_name
  namespace       = "kube-system"
  service_account = "aws-load-balancer-controller"
  role_arn        = aws_iam_role.lb_controller.arn

  depends_on = [module.eks_app]
}

# --- LLM-serving workloads (LLM cluster) — S3 read for model artifacts.
# EFS access itself is security-group-based (NFS mount), not IAM, so this
# role only needs S3 — added here because nothing granted the LLM pods
# ANY AWS access before this. ---

resource "aws_iam_role" "llm_serving" {
  name               = "${var.project_name}-llm-serving"
  assume_role_policy = data.aws_iam_policy_document.pod_identity_trust.json
}

data "aws_iam_policy_document" "llm_serving" {
  statement {
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${module.data_services.model_artifacts_bucket}",
      "arn:aws:s3:::${module.data_services.model_artifacts_bucket}/*",
    ]
  }
}

resource "aws_iam_role_policy" "llm_serving" {
  name   = "${var.project_name}-llm-serving"
  role   = aws_iam_role.llm_serving.id
  policy = data.aws_iam_policy_document.llm_serving.json
}

resource "aws_eks_pod_identity_association" "llm_serving" {
  cluster_name    = module.eks_llm.cluster_name
  namespace       = "default"
  service_account = "llm-serving"
  role_arn        = aws_iam_role.llm_serving.arn

  depends_on = [module.eks_llm]
}
