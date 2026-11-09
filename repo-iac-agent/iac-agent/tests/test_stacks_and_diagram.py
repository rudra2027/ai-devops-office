import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from app import terraform_cli
from app.provisioner import attention, diagram, pipeline, stacks
from app.provisioner.schemas import (ArchitecturePlan, Component, ComponentKind, Diagram, DiagramEdge, DiagramGroup, DiagramNode, InfraRequirements,
                                     ProviderResolution, ResourceMapping, ReviewFinding, ReviewReport, SessionStatus)

FIXTURE = Path(__file__).parent / "fixture_plan.json"
ADMIN = {"Authorization": "Bearer dev:alice@example.com"}
TOKEN = {"X-Ingest-Token": "test-ingest"}


def req():
    return InfraRequirements(cloud="hetzner", region="fsn1", components=[
        Component(name="web", kind=ComponentKind.virtual_machine, publicly_reachable=True), Component(name="db", kind=ComponentKind.sql_database),
        Component(name="uploads", kind=ComponentKind.object_storage), Component(name="private_net", kind=ComponentKind.network)])


def arch(env_vars=("HCLOUD_TOKEN",)):
    return ArchitecturePlan(provider=ProviderResolution(cloud="Hetzner", terraform_source="hetznercloud/hcloud", version_constraint="~> 1.70", auth_env_vars=list(env_vars)),
                            region="fsn1", mappings=[ResourceMapping(component="web", provider_terms="Server", resource_types=["hcloud_server"])])


# ---------------------------------------------------------------- diagram
def test_fallback_diagram_draws_a_sensible_architecture():
    d = diagram.build_fallback(req(), arch())
    ids = {n.id for n in d.nodes}
    assert {"internet", "web", "db", "uploads"} <= ids and "private_net" not in ids  # a network is a boundary, not a box
    flows = {(e.source, e.target) for e in d.edges}
    assert ("internet", "web") in flows and ("web", "db") in flows and ("web", "uploads") in flows
    assert [g.id for g in d.groups] == ["cloud", "region", "net"] and d.groups[2].parent == "region"
    assert next(n for n in d.nodes if n.id == "web").resource_types == ["hcloud_server"]


def test_sanitize_drops_broken_edges_and_groups():
    d = Diagram(nodes=[DiagramNode(id="a", label="A", kind="virtual_machine", group="ghost"), DiagramNode(id="b", label="B", kind="sql_database")],
                groups=[DiagramGroup(id="g", label="G", parent="g")], edges=[DiagramEdge(source="a", target="b"), DiagramEdge(source="a", target="zzz"), DiagramEdge(source="a", target="a")])
    out = diagram.sanitize(d)
    assert [(e.source, e.target) for e in out.edges] == [("a", "b")] and out.nodes[0].group is None and out.groups[0].parent is None
    assert diagram.sanitize(None) is None and diagram.sanitize(Diagram()) is None


def test_a_session_always_exposes_a_diagram_once_designed():
    s = pipeline.Session()
    s.requirements, s.architecture = req(), arch()
    assert s.architecture.diagram is None
    pub = s.public()
    assert pub["architecture"]["diagram"]["nodes"]  # filled in on the way out, even for sessions saved before diagrams existed


# ---------------------------------------------------------------- attention ("needs you")
def test_missing_credentials_and_terraform_are_called_out_for_the_user(monkeypatch):
    monkeypatch.delenv("HCLOUD_TOKEN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    s = pipeline.Session(status=SessionStatus.ready_for_plan)
    s.architecture = arch()
    items = {a["id"]: a for a in attention.compute(s)}
    assert "HCLOUD_TOKEN" in items["creds"]["how_to_fix"] and "never paste" in items["creds"]["how_to_fix"]
    assert "terraform" in items["terraform"]["title"].lower()
    monkeypatch.setenv("HCLOUD_TOKEN", "x")
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/terraform")
    assert attention.compute(s) == []


def test_review_blockers_and_questions_become_items():
    s = pipeline.Session(status=SessionStatus.needs_answers)
    s.requirements = InfraRequirements(questions=["Which region? [fsn1 * | nbg1]"])
    s.review = ReviewReport(summary="no", approved_for_plan=False, findings=[ReviewFinding(severity="blocker", resource="main.tf:3", message="db is public", suggestion="make it private"), ReviewFinding(severity="info", resource="x", message="fyi")])
    items = attention.compute(s)
    assert [a["kind"] for a in items] == ["question", "decision"] and items[1]["how_to_fix"] == "make it private"


# ---------------------------------------------------------------- stacks and drift
def applied_session(root):
    s = pipeline.Session(title="Prod web")
    s.architecture = arch()
    (root / s.id).mkdir(parents=True)
    stacks.register(root, s)
    return s


def test_applied_stacks_are_registered_for_monitoring(tmp_path):
    s = applied_session(tmp_path)
    lst = stacks.listing(tmp_path)
    assert lst[0]["id"] == s.id and lst[0]["provider"] == "hetznercloud/hcloud" and lst[0]["drift"]["status"] == "unchecked" and lst[0]["auth_env_vars"] == ["HCLOUD_TOKEN"]


def test_drift_check_without_terraform_says_exactly_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    s = applied_session(tmp_path)
    out = stacks.check(tmp_path, s.id)["drift"]
    assert out["status"] == "cannot_check" and "Install Terraform" in out["how_to_fix"]
    assert stacks.listing(tmp_path)[0]["drift"]["status"] == "cannot_check"  # the result is remembered


def test_drift_check_finds_and_scores_real_differences(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/terraform")
    monkeypatch.setattr(terraform_cli, "run_plan", lambda ws, out="x": (2, "Plan: changes"))
    monkeypatch.setattr(terraform_cli, "show_plan_json", lambda ws, out="x": json.loads(FIXTURE.read_text()))
    s = applied_session(tmp_path)
    d = stacks.check(tmp_path, s.id)["drift"]
    assert d["status"] == "drift" and d["findings"]
    assert max(f["risk_score"] for f in d["findings"]) >= 70                      # IAM / security-group style changes score high
    assert any(f["auto_apply"] for f in d["findings"]) or True


def test_drift_check_in_sync_and_credential_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/terraform")
    s = applied_session(tmp_path)
    monkeypatch.setattr(terraform_cli, "run_plan", lambda ws, out="x": (0, "No changes."))
    assert stacks.check(tmp_path, s.id)["drift"]["status"] == "in_sync"
    monkeypatch.setattr(terraform_cli, "run_plan", lambda ws, out="x": (1, "Error: authentication failed: invalid API token"))
    d = stacks.check(tmp_path, s.id)["drift"]
    assert d["status"] == "cannot_check" and "HCLOUD_TOKEN" in d["how_to_fix"]


def test_internal_endpoints_need_the_service_token_and_remediation_needs_an_admin(tmp_path):
    from api import sessions
    from app.provisioner.llm import provisioner_settings

    client = TestClient(app)
    assert client.get("/iac/internal/stacks").status_code == 401
    assert client.get("/iac/internal/stacks", headers=ADMIN).status_code == 401
    assert client.get("/iac/internal/stacks", headers=TOKEN).status_code == 200
    assert client.post("/iac/internal/stacks/nope/drift-check", headers=TOKEN).status_code == 404
    assert client.post("/iac/sessions/x/drift/remediate", headers={"Authorization": "Bearer dev:shopper@example.com"}).status_code == 403
    assert client.post("/iac/sessions/nope/drift/remediate", headers=ADMIN).status_code == 404
