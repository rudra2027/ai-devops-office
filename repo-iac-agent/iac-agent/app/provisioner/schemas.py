"""
Pydantic contracts between the provisioning colleagues. Everything the LLM
produces is validated against one of these; nothing here names a cloud.
Cloud-specific vocabulary only ever appears as free-text strings the LLM
fills in after looking things up (see tools.py), so adding a new cloud needs
no code change.
"""

from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ComponentKind(str, Enum):
    network = "network"
    virtual_machine = "virtual_machine"
    kubernetes_cluster = "kubernetes_cluster"
    container_service = "container_service"
    serverless_function = "serverless_function"
    object_storage = "object_storage"
    block_storage = "block_storage"
    sql_database = "sql_database"
    nosql_database = "nosql_database"
    cache = "cache"
    message_queue = "message_queue"
    load_balancer = "load_balancer"
    cdn = "cdn"
    dns = "dns"
    firewall = "firewall"
    secrets = "secrets"
    identity = "identity"
    monitoring = "monitoring"
    other = "other"


class Component(BaseModel):
    """A cloud-neutral building block the user asked for."""

    name: str = Field(..., description="Short snake_case name, e.g. 'app_db'")
    kind: ComponentKind
    description: str = Field("", description="What the user wants from it, in their words")
    size_hint: Optional[str] = Field(None, description="e.g. '2 vCPU / 4 GB', 'small', '100 GB'")
    count: int = Field(1, ge=1)
    high_availability: bool = False
    publicly_reachable: bool = False
    options: Dict[str, str] = Field(default_factory=dict, description="Engine, version, ports, etc.")


class InfraRequirements(BaseModel):
    cloud: Optional[str] = Field(
        None, description="Cloud/vendor exactly as the user named it (any cloud). None if never stated."
    )
    region: Optional[str] = Field(None, description="Region/location as the user said it")
    environment: str = "dev"
    components: List[Component] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list, description="Budget, compliance, latency, etc.")
    questions: List[str] = Field(
        default_factory=list,
        description="Questions to ask the user BEFORE designing. Only blocking ones: cloud unknown, "
        "nothing concrete to build, or a contradiction. Leave empty if sensible defaults exist.",
    )


class ProviderResolution(BaseModel):
    cloud: str
    terraform_source: str = Field(..., description="Registry address, e.g. 'hetznercloud/hcloud'")
    version_constraint: str = Field(..., description="e.g. '~> 1.70'")
    auth_env_vars: List[str] = Field(
        default_factory=list, description="Env vars the provider reads for credentials. Never values."
    )


class ResourceMapping(BaseModel):
    component: str
    provider_terms: str = Field(
        ..., description="How this cloud names the concept, e.g. 'Azure calls a VPC a Virtual Network'"
    )
    resource_types: List[str] = Field(..., description="Terraform resource types that implement it")
    notes: str = ""


class DiagramNode(BaseModel):
    id: str = Field(..., description="short snake_case id, unique in the diagram")
    label: str
    kind: str = Field(..., description="a component kind (virtual_machine, sql_database, object_storage, load_balancer, ...) or 'internet' or 'users'")
    resource_types: List[str] = Field(default_factory=list, description="Terraform resource types behind this box")
    group: Optional[str] = Field(None, description="id of the boundary it sits inside")
    note: str = ""


class DiagramGroup(BaseModel):
    id: str
    label: str
    kind: str = Field("other", description="cloud, region, network, subnet, zone or other")
    parent: Optional[str] = Field(None, description="id of the enclosing group")


class DiagramEdge(BaseModel):
    source: str
    target: str
    label: str = Field("", description="what flows, e.g. HTTPS, SQL, reads/writes")


class Diagram(BaseModel):
    title: str = ""
    nodes: List[DiagramNode] = Field(default_factory=list)
    groups: List[DiagramGroup] = Field(default_factory=list, description="cloud > region > network boundaries")
    edges: List[DiagramEdge] = Field(default_factory=list, description="traffic or data flows between nodes")


class ArchitecturePlan(BaseModel):
    provider: ProviderResolution
    region: str
    mappings: List[ResourceMapping]
    gaps: List[str] = Field(
        default_factory=list,
        description="Things this cloud cannot do natively and how they are worked around",
    )
    diagram: Optional[Diagram] = Field(None, description="Architecture diagram: a node per component plus 'internet' if anything is public, groups for cloud > region > network, edges for flows")


class TerraformFile(BaseModel):
    path: str = Field(..., description="Relative path such as 'main.tf'. No directories above the root.")
    content: str


class GeneratedStack(BaseModel):
    files: List[TerraformFile]
    summary: str
    assumptions: List[str] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    severity: Literal["info", "warning", "blocker"]
    resource: str
    message: str
    suggestion: str = ""


class ReviewReport(BaseModel):
    findings: List[ReviewFinding] = Field(default_factory=list)
    summary: str
    approved_for_plan: bool = Field(
        ..., description="False if any blocker remains. The human still has the final say."
    )


class SessionStatus(str, Enum):
    collecting = "collecting"
    needs_answers = "needs_answers"
    designing = "designing"
    ready_for_plan = "ready_for_plan"
    planned = "planned"
    approved = "approved"
    applying = "applying"
    applied = "applied"
    failed = "failed"
