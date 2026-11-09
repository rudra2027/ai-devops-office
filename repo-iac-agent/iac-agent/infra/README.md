# Infrastructure — Terraform

Real Terraform for Phase 2 of the build guide: two EKS clusters (LLM +
application), ECS Fargate frontend, CloudFront, and the shared data
services (EFS, Secrets Manager, S3, DynamoDB findings table, SQS).

## Status

This is real, structurally-validated HCL — every module and the full
environment root parse cleanly with `terraform-config-inspect`, and all 34
cross-module output references were checked to actually resolve (including
the two separate `eks` instantiations below). It has **not** been applied
against a real AWS account — no credentials exist in the environment this
was built in. `terraform init`/`plan`/`apply` against real AWS is the next
step, on your machine, with your credentials (see providers.tf below).

## Architecture: two EKS clusters, not one

- **`chatbot-agent-llm`** — hosts the LLM GPU pods (vLLM/TGI), Audio8 TTS
  (CPU), and the LiteLLM/Omni-Route proxy. Single environment, no
  blue/green — model serving doesn't carry the same deploy-safety
  requirement the application does, and this keeps the LLM cluster simpler.
- **`chatbot-agent-app`** — hosts the chatbot backend/agent and the IaC
  agent. Has `blue` and `green` namespaces (created directly by Terraform
  via the `kubernetes` provider, in `pod-identity.tf`) for the blue/green
  deploys Argo Rollouts will manage in Phase 8.

Both share one VPC (one NAT gateway, not two — the VPC module tags every
subnet with both clusters' `kubernetes.io/cluster/<name>` discovery tags).

## providers.tf — how Terraform reaches your AWS account

All provider/backend config lives in `environments/dev/providers.tf`, not
scattered across files. Real credentials never go directly in that file —
they go in `terraform.tfvars`, which is gitignored, same pattern as `.env`
everywhere else in this project.

```bash
cd environments/dev
cp terraform.tfvars.example terraform.tfvars
```

Pick one authentication method (in order of preference — see
`providers.tf`'s header comment for the full reasoning):

1. **AWS CLI profile** — `aws configure`, then set `aws_profile` in
   `terraform.tfvars`.
2. **Environment variables** — `export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...`
   in your shell; leave `terraform.tfvars` empty. The AWS provider picks
   these up automatically.
3. **Explicit keys in terraform.tfvars** — least preferred; a plaintext
   credential in any file, even a gitignored one, is a real exposure risk.
   Only use this if neither option above works for you.

The `kubernetes` provider (needed for the blue/green namespace resources)
authenticates against the **app cluster specifically**, using a
`data "aws_eks_cluster_auth"` token — this only works once the app
cluster exists, which is fine since it's created in the same `apply`.

## Cost warning before you `apply` anything

This is not free-tier-only infrastructure, and now creates **two** EKS
control planes instead of one:
- Two EKS control planes bill hourly each, regardless of node count.
- The NAT gateway bills hourly plus per-GB.
- Any GPU nodes you add later (`infra/k8s/gpu-nodepool.yaml`, applied to
  the LLM cluster specifically via kubectl once it exists) are the most
  expensive part of this whole project by far. The NodePool is configured
  to scale to zero when idle (`consolidateAfter: 5m`) — verify it's
  actually doing that once running, don't just trust the config.

Run `terraform destroy` when you're done with a session of testing, or set
a billing alert, or both.

## Order of operations

### 1. Bootstrap the state backend (once, ever)

```bash
cd bootstrap
terraform init
terraform apply
```

Note the two outputs — `state_bucket_name` and `lock_table_name`.

### 2. Configure the dev environment

```bash
cd ../environments/dev
cp backend.hcl.example backend.hcl
cp terraform.tfvars.example terraform.tfvars
```

Fill in `backend.hcl` with the bucket/table names from step 1, and
`terraform.tfvars` per the providers.tf section above.

### 3. Init and plan

```bash
terraform init -backend-config=backend.hcl
terraform plan
```

Read the plan output before applying — standard practice, but especially
worth it the first time given the cost note above and that this now
creates two clusters at once.

### 4. Apply

```bash
terraform apply
```

### 5. Apply the GPU NodePool to the LLM cluster specifically

```bash
aws eks update-kubeconfig --name chatbot-agent-llm --region ap-south-1
kubectl apply -f ../k8s/gpu-nodepool.yaml
```

Kubernetes custom resource, not a Terraform resource — make sure your
kubeconfig context is pointed at the **LLM** cluster, not the app cluster,
before running this.

## Module layout

- `bootstrap/` — S3 + DynamoDB state backend. Uses local state itself
  (chicken-and-egg — can't use the backend it's creating).
- `modules/vpc/` — public/private subnets across 2 AZs, single NAT
  gateway, NACLs, discovery tags for however many clusters share it
  (`cluster_names` variable — currently two).
- `modules/eks/` — EKS Auto Mode cluster, OIDC provider, cluster + node
  IAM roles, `eks-pod-identity-agent` addon (required for Pod Identity
  Association to function at all — not something Auto Mode manages for
  you). Instantiated **twice** in `environments/dev/main.tf` (`eks_llm`,
  `eks_app`) — same module, two separate clusters.
- `modules/ecs-frontend/` — ALB + Fargate service for the chat/ops
  dashboard frontend.
- `modules/cdn/` — CloudFront distribution in front of the frontend ALB.
- `modules/data-services/` — EFS (model weights), Secrets Manager secret
  slots, S3 (model artifacts), DynamoDB (IaC agent findings table),
  SQS + DLQ. Shared by both clusters.
- `environments/dev/` — wires everything together:
  - `main.tf` — module calls + outputs
  - `providers.tf` — terraform/backend/provider config + AWS auth variables
  - `pod-identity.tf` — IAM roles + Pod Identity Associations for 4
    workloads (`chatbot-backend` ×2 for blue/green, `iac-agent`,
    `lb-controller`, `llm-serving`), plus the blue/green namespace objects

Only environment that exists so far — a `prod/` is still open per the
build guide's "open decisions" section.

## What's still a placeholder

- `frontend_image` defaults to a public nginx image — replace with your
  real ECR URI once Phase 3/7 push one.
- `backend_url` passed to the frontend module is a placeholder string —
  becomes the real app cluster Ingress URL once that exists (Phase 6).
- Secrets Manager secret *values* aren't set by Terraform at all, by
  design — populate real values via the AWS CLI/console or CI, never in
  a `.tf`/`.tfvars` file.
- The AWS Load Balancer Controller's IAM policy (`pod-identity.tf`) is a
  representative subset — cross-check against the authoritative policy in
  the `kubernetes-sigs/aws-load-balancer-controller` repo before relying
  on it for a real deployment.
