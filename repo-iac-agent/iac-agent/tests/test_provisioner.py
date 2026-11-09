"""
Provisioner tests with a scripted LLM, so no model, terraform or cloud is
needed. The live-registry test is skipped when offline.
"""

import itertools

import httpx
import pytest
from langchain_core.messages import AIMessage

from app.provisioner import checks, pipeline, registry
from app.provisioner.llm_loop import StageFailed, run_stage
from app.provisioner.schemas import InfraRequirements, SessionStatus, TerraformFile

_ids = itertools.count()


def call(name, **args):
    return {"name": name, "args": args, "id": f"c{next(_ids)}", "type": "tool_call"}


class ScriptedLLM:
    """Returns pre-baked AIMessages in order, regardless of input."""

    def __init__(self, *messages):
        self.messages = list(messages)

    def bind_tools(self, tools):
        return self

    def invoke(self, _):
        return self.messages.pop(0)


GOOD_TF = '''
terraform {
  required_providers {
    hcloud = { source = "hetznercloud/hcloud", version = "~> 1.70" }
  }
}
variable "db_password" {
  type      = string
  sensitive = true
}
resource "hcloud_server" "app" {
  name        = "app"
  server_type = "cx22"
  image       = "ubuntu-24.04"
}
'''


def full_script():
    return ScriptedLLM(
        AIMessage(content="", tool_calls=[call("InfraRequirements", cloud="hetzner", region="fsn1",
                  components=[{"name": "app", "kind": "virtual_machine"}])]),
        AIMessage(content="", tool_calls=[call("search_terraform_providers", query="hetzner")]),
        AIMessage(content="", tool_calls=[call("ArchitecturePlan",
                  provider={"cloud": "hetzner", "terraform_source": "hetznercloud/hcloud",
                            "version_constraint": "~> 1.70", "auth_env_vars": ["HCLOUD_TOKEN"]},
                  region="fsn1",
                  mappings=[{"component": "app", "provider_terms": "Server", "resource_types": ["hcloud_server"]}])]),
        AIMessage(content="", tool_calls=[call("GeneratedStack", summary="One server.",
                  files=[{"path": "main.tf", "content": GOOD_TF}])]),
        AIMessage(content="", tool_calls=[call("ReviewReport", summary="Looks fine.", approved_for_plan=True)]),
    )


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch):
    monkeypatch.setattr(registry, "search_providers", lambda q, limit=8: [{"source": "hetznercloud/hcloud"}])


def test_full_pipeline_ready_for_plan():
    s = pipeline.Session()
    pipeline.handle_message(s, "A server on Hetzner in Falkenstein", full_script(), use_terraform=False)
    assert s.status == SessionStatus.ready_for_plan, s.error
    assert s.architecture.provider.terraform_source == "hetznercloud/hcloud"
    assert [f.path for f in s.stack.files] == ["main.tf"]


def test_missing_cloud_asks_questions_instead_of_guessing():
    llm = ScriptedLLM(AIMessage(content="", tool_calls=[call(
        "InfraRequirements", questions=["Which cloud?"], components=[{"name": "db", "kind": "sql_database"}])]))
    s = pipeline.Session()
    pipeline.handle_message(s, "I need a database", llm, use_terraform=False)
    assert s.status == SessionStatus.needs_answers
    assert "Which cloud?" in s.history[-1][1]


def test_invalid_submit_is_sent_back_for_repair():
    llm = ScriptedLLM(
        AIMessage(content="", tool_calls=[call("InfraRequirements", components=[{"name": "x", "kind": "not_a_kind"}])]),
        AIMessage(content="", tool_calls=[call("InfraRequirements", cloud="oci", components=[])]),
    )
    out = run_stage(llm, system="s", user="u", tools=[], submit=InfraRequirements, member="requirements",
                    emit=lambda *a, **k: None)
    assert out.cloud == "oci"


def test_stage_fails_when_model_never_submits():
    llm = ScriptedLLM(AIMessage(content="hello"), AIMessage(content="still talking"))
    with pytest.raises(StageFailed):
        run_stage(llm, system="s", user="u", tools=[], submit=InfraRequirements, member="requirements",
                  emit=lambda *a, **k: None)


def test_hardcoded_secret_is_a_blocker_even_if_llm_approves():
    bad = GOOD_TF + '\nresource "x_db" "d" {\n  password = "hunter2hunter2"\n}\n'
    script = full_script()
    script.messages[3] = AIMessage(content="", tool_calls=[call("GeneratedStack", summary="s",
                                   files=[{"path": "main.tf", "content": bad}])])
    s = pipeline.Session()
    pipeline.handle_message(s, "server", script, use_terraform=False)
    assert s.review is not None and not s.review.approved_for_plan
    assert s.status == SessionStatus.needs_answers


def test_unsafe_paths_rejected():
    for p in ["../evil.tf", "/etc/x.tf", "C:\\x.tf", "a/../../b.tf", "run.exe"]:
        with pytest.raises(ValueError):
            checks.safe_path(p)
    assert checks.safe_path("modules/net/main.tf") == "modules/net/main.tf"


def test_hcl_syntax_error_reported():
    ok, msg = checks.validate_terraform([TerraformFile(path="main.tf", content='resource "a" "b" {')], use_terraform=False)
    assert not ok and "main.tf" in msg


def test_apply_requires_approval(tmp_path):
    from app.provisioner import operator

    s = pipeline.Session(status=SessionStatus.planned)
    with pytest.raises(operator.OperatorError):
        operator.apply(s, tmp_path)
    operator.approve(s, "alice")
    assert s.status == SessionStatus.approved and s.approved_by == "alice"


@pytest.mark.network
def test_registry_resolves_a_non_big3_cloud():
    try:
        found = registry.search_providers("hetzner")
        names = registry.list_resources("hetznercloud/hcloud", "server")
    except registry.RegistryError as exc:
        if isinstance(exc.__cause__, httpx.HTTPError):
            pytest.skip("offline")
        raise
    assert any(p["source"] == "hetznercloud/hcloud" for p in found)
    assert "hcloud_server" in names
    assert "server_type" in registry.resource_doc("hetznercloud/hcloud", "hcloud_server")
