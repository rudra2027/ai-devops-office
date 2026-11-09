"""
Architecture diagram for a design. The architect colleague proposes one (nodes, boundaries, flows); `sanitize` drops anything
inconsistent, and `build_fallback` derives a sensible diagram from the requirements when the model gave none. Either way
there is always something to draw.
"""

from typing import Dict, List, Optional

from .schemas import ArchitecturePlan, Diagram, DiagramEdge, DiagramGroup, DiagramNode, InfraRequirements

# typical direction of traffic / data, used for the fallback diagram
_ENTRY = ["cdn", "dns", "load_balancer"]
_COMPUTE = ["virtual_machine", "container_service", "kubernetes_cluster", "serverless_function"]
_DATA = ["sql_database", "nosql_database", "cache", "object_storage", "block_storage", "message_queue"]


def sanitize(d: Optional[Diagram]) -> Optional[Diagram]:
    if d is None or not d.nodes:
        return None
    ids = {n.id for n in d.nodes}
    groups = {g.id for g in d.groups}
    for n in d.nodes:
        if n.group not in groups:
            n.group = None
    for g in d.groups:
        if g.parent not in groups or g.parent == g.id:
            g.parent = None
    d.edges = [e for e in d.edges if e.source in ids and e.target in ids and e.source != e.target]
    return d


def build_fallback(req: InfraRequirements, arch: Optional[ArchitecturePlan]) -> Diagram:
    by_name = {m.component: m for m in (arch.mappings if arch else [])}
    nodes: List[DiagramNode] = []
    kinds: Dict[str, List[str]] = {}
    cloud = (arch.provider.cloud if arch else req.cloud) or "cloud"
    region = (arch.region if arch else req.region) or "region"
    groups = [DiagramGroup(id="cloud", label=cloud, kind="cloud"), DiagramGroup(id="region", label=region, kind="region", parent="cloud")]
    has_net = any(c.kind.value == "network" for c in req.components)
    if has_net:
        groups.append(DiagramGroup(id="net", label="Private network", kind="network", parent="region"))
    for c in req.components:
        m = by_name.get(c.name)
        k = c.kind.value
        if k == "network":
            continue  # drawn as a boundary, not a box
        nodes.append(DiagramNode(id=c.name, label=c.name.replace("_", " "), kind=k, resource_types=m.resource_types if m else [], group="net" if has_net and k in _COMPUTE + _DATA else "region",
                                 note=(f"{c.size_hint}, " if c.size_hint else "") + (f"x{c.count}" if c.count > 1 else "")))
        kinds.setdefault(k, []).append(c.name)
    public = any(c.publicly_reachable for c in req.components) or any(k in kinds for k in _ENTRY)
    if public:
        nodes.insert(0, DiagramNode(id="internet", label="Internet", kind="internet", group=None))
    edges: List[DiagramEdge] = []

    def link(srcs: List[str], dsts: List[str], label: str = "") -> None:
        for s in srcs:
            for d in dsts:
                edges.append(DiagramEdge(source=s, target=d, label=label))

    entry = [n for k in _ENTRY for n in kinds.get(k, [])]
    compute = [n for k in _COMPUTE for n in kinds.get(k, [])]
    data = [n for k in _DATA for n in kinds.get(k, [])]
    if public:
        link(["internet"], entry or compute, "HTTPS")
    if entry and compute:
        link(entry, compute, "forwards")
    sql = [n for k in ("sql_database", "nosql_database") for n in kinds.get(k, [])]
    other = [n for n in data if n not in sql]
    if compute and sql:
        link(compute, sql, "queries")
    if compute and other:
        link(compute, other, "reads / writes")
    for s in kinds.get("secrets", []):
        if compute:
            link(compute, [s], "gets secrets")
    return sanitize(Diagram(title=f"{req.environment} on {cloud}", nodes=nodes, groups=groups, edges=edges)) or Diagram(title="Architecture", nodes=nodes, groups=groups, edges=[])
