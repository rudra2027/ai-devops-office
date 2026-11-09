import asyncio
import itertools
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app import designer, watch
from app.dashboards import BUILTIN, Dashboard, validate_dashboard
from app.engine import CATALOG, Engine, MetricQuery
from app.main import app, engine, watcher

ADMIN = {"Authorization": "Bearer dev:alice@example.com"}
CUSTOMER = {"Authorization": "Bearer dev:shopper@example.com"}
TOKEN = {"X-Ingest-Token": "test-token"}
_ids = itertools.count()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def sample(service="support", cpu=10.0, mem=100.0, **kw):
    return {"service": service, "ts": time.time(), "cpu_percent": cpu, "memory_mb": mem, "rps": 2.0, "requests": 20, "latency_p95_ms": 120.0,
            "error_rate": 0.0, "inflight": 1, "loop_lag_ms": 2.0, "threads": 8, "handles": 100, "uptime_s": 60, **kw}


# ------------------------------------------------------------------ metrics: ingest, catalog, query
def test_metric_ingest_needs_the_service_token(client):
    assert client.post("/api/metrics/ingest", json=sample()).status_code == 401
    assert client.post("/api/metrics/ingest", json=sample(), headers={"X-Ingest-Token": "nope"}).status_code == 401
    assert client.post("/api/metrics/ingest", json=sample(), headers=TOKEN).status_code == 200
    assert client.post("/api/metrics/ingest", json={"cpu_percent": 1}, headers=TOKEN).status_code == 422


def test_metric_reads_are_admin_only(client):
    for method, path in (("get", "/api/metrics/catalog"), ("get", "/api/platform"), ("get", "/api/incidents"), ("get", "/api/delivery"), ("get", "/api/drift"),
                         ("get", "/api/dashboards"), ("post", "/api/drift/check")):
        assert getattr(client, method)(path, headers=CUSTOMER).status_code == 403, path
    assert client.post("/api/metrics/query", json={"metric": "service.cpu_percent"}, headers=CUSTOMER).status_code == 403


def test_query_cpu_by_service_and_filters(client):
    client.post("/api/metrics/ingest", json=sample("support", cpu=20), headers=TOKEN)
    client.post("/api/metrics/ingest", json=sample("iac", cpu=40), headers=TOKEN)
    r = client.post("/api/metrics/query", json={"metric": "service.cpu_percent", "by": "service", "window": "15m", "agg": "max"}, headers=ADMIN).json()
    assert r["value"]["iac"] == 40 and r["value"]["support"] >= 20 and r["unit"] == "%"
    one = client.post("/api/metrics/query", json={"metric": "service.cpu_percent", "where": {"service": "iac"}, "agg": "last"}, headers=ADMIN).json()
    assert one["value"] == 40 and one["series"][0]["name"] == "iac"


def test_query_rejects_nonsense_with_a_helpful_message(client):
    def bad(body):
        r = client.post("/api/metrics/query", json=body, headers=ADMIN)
        assert r.status_code == 422
        return r.json()["detail"]

    assert "Unknown metric" in bad({"metric": "service.vibes"})
    assert "Unknown window" in bad({"metric": "service.cpu_percent", "window": "3y"})
    assert "Unknown aggregation" in bad({"metric": "service.cpu_percent", "agg": "median"})
    assert "cannot be split" in bad({"metric": "host.cpu_percent", "by": "service"})
    assert "cannot be filtered" in bad({"metric": "service.cpu_percent", "where": {"colour": "red"}})


def test_every_catalog_metric_can_be_queried_without_error(client):
    for key in CATALOG:
        assert client.post("/api/metrics/query", json={"metric": key, "window": "1h"}, headers=ADMIN).status_code == 200, key


def test_catalog_is_self_describing(client):
    c = client.get("/api/metrics/catalog", headers=ADMIN).json()
    keys = {m["key"] for m in c["metrics"]}
    assert {"service.cpu_percent", "service.memory_mb", "service.latency_p95_ms", "llm.cost_usd", "cicd.success_rate", "drift.open_findings"} <= keys
    assert all(m["description"] and m["group"] for m in c["metrics"])


def test_platform_snapshot_reports_each_service(client):
    client.post("/api/metrics/ingest", json=sample("cicd", cpu=5), headers=TOKEN)
    engine.tsdb.add("service.up", "cicd", time.time(), 1.0)
    p = client.get("/api/platform", headers=ADMIN).json()
    assert p["services"]["cicd"]["up"] is True and p["services"]["cicd"]["cpu_percent"] == 5 and p["services"]["cicd"]["label"]
    assert {"cpu_percent", "memory_percent", "disk_percent"} <= set(p["host"])


# ------------------------------------------------------------------ dashboards
def test_builtin_dashboards_only_use_catalog_metrics():
    for d in BUILTIN:
        assert not validate_dashboard(Dashboard.model_validate(d), Engine()), d["title"]


def test_dashboard_lifecycle_and_validation(client):
    good = {"title": "Support health", "description": "d", "widgets": [
        {"type": "stat", "title": "CPU", "queries": [{"metric": "service.cpu_percent", "where": {"service": "support"}}], "width": 1},
        {"type": "timeseries", "title": "p95", "queries": [{"metric": "service.latency_p95_ms", "by": "service"}]}]}
    r = client.post("/api/dashboards", json=good, headers=ADMIN)
    assert r.status_code == 201
    did = r.json()["id"]
    assert did in [d["id"] for d in client.get("/api/dashboards", headers=ADMIN).json()]
    assert client.get(f"/api/dashboards/{did}", headers=ADMIN).json()["widgets"][0]["title"] == "CPU"

    bad = {**good, "widgets": [{"type": "stat", "title": "x", "queries": [{"metric": "service.vibes"}]}]}
    assert client.post("/api/dashboards", json=bad, headers=ADMIN).status_code == 422
    assert client.post("/api/dashboards", json={**good, "widgets": [{"type": "stat", "title": "no query", "queries": []}]}, headers=ADMIN).status_code == 422
    assert client.post("/api/dashboards", json={**good, "widgets": [{"type": "stat", "title": "two", "queries": [{"metric": "host.cpu_percent"}, {"metric": "host.memory_percent"}]}]}, headers=ADMIN).status_code == 422

    assert client.put(f"/api/dashboards/{did}", json={**good, "title": "Renamed"}, headers=ADMIN).json()["title"] == "Renamed"
    rendered = client.post("/api/dashboards/render", json=good, headers=ADMIN).json()
    assert len(rendered["widgets"]) == 2 and rendered["widgets"][0][0]["metric"] == "service.cpu_percent"
    assert client.delete(f"/api/dashboards/{did}", headers=ADMIN).status_code == 200
    assert client.get(f"/api/dashboards/{did}", headers=ADMIN).status_code == 404
    assert client.delete("/api/dashboards/builtin-llm", headers=ADMIN).status_code == 409
    assert client.put("/api/dashboards/builtin-llm", json=good, headers=ADMIN).status_code == 409


class ScriptedLLM:
    def __init__(self, *msgs):
        self.msgs = list(msgs)

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, *a, **k):
        return self.msgs.pop(0)


def reply(**args):
    return AIMessage(content="", tool_calls=[{"name": "DesignerReply", "args": args, "id": f"c{next(_ids)}", "type": "tool_call"}])


def test_designer_asks_all_its_questions_first(monkeypatch):
    qs = [{"text": "Which services? [support * | all]", "options": ["support", "all"]}, {"text": "Time range?", "options": ["1h", "6h"]}]
    monkeypatch.setattr(designer, "get_chat_model", lambda *a, **k: ScriptedLLM(reply(mode="ask", message="Two quick questions.", questions=qs)))
    out = asyncio.run(designer.design(Engine(), [{"role": "user", "content": "make me a dashboard"}], None))
    assert out["mode"] == "ask" and len(out["questions"]) == 2 and out["dashboard"] is None


def test_designer_must_use_catalog_metrics_and_gets_a_chance_to_fix_its_mistakes(monkeypatch):
    wrong = {"title": "T", "widgets": [{"type": "stat", "title": "x", "queries": [{"metric": "service.happiness"}]}]}
    right = {"title": "T", "widgets": [{"type": "stat", "title": "x", "queries": [{"metric": "service.cpu_percent"}]}]}
    llm = ScriptedLLM(reply(mode="dashboard", message="here", dashboard=wrong), reply(mode="dashboard", message="fixed", dashboard=right))
    monkeypatch.setattr(designer, "get_chat_model", lambda *a, **k: llm)
    out = asyncio.run(designer.design(Engine(), [{"role": "user", "content": "cpu please"}], None))
    assert out["mode"] == "dashboard" and out["dashboard"]["widgets"][0]["queries"][0]["metric"] == "service.cpu_percent"


def test_designer_gives_up_cleanly_after_repeated_mistakes(monkeypatch):
    wrong = {"title": "T", "widgets": [{"type": "stat", "title": "x", "queries": [{"metric": "nope"}]}]}
    monkeypatch.setattr(designer, "get_chat_model", lambda *a, **k: ScriptedLLM(*[reply(mode="dashboard", message="m", dashboard=wrong) for _ in range(3)]))
    with pytest.raises(RuntimeError):
        asyncio.run(designer.design(Engine(), [{"role": "user", "content": "x"}], None))


# ------------------------------------------------------------------ watchers
def fresh_watch():
    e = Engine()
    return e, watch.Watch(e)


def test_service_down_needs_two_failed_probes_then_resolves():
    e, w = fresh_watch()
    now = time.time()
    e.tsdb.add("service.up", "iac", now, 0.0)
    asyncio.run(w.platform_tick())
    assert not w.incidents                                     # one failed probe is not an outage
    asyncio.run(w.platform_tick())
    inc = w.incidents["down:iac"]
    assert inc["needs_user"] and inc["severity"] == "critical" and "start" in inc["how_to_fix"].lower()
    e.tsdb.add("service.up", "iac", now + 1, 1.0)
    asyncio.run(w.platform_tick())
    assert "down:iac" not in w.incidents and w.resolved[0]["key"] == "down:iac"


def test_pressure_rules_fire_for_cpu_memory_latency_and_errors():
    e, w = fresh_watch()
    now = time.time()
    e.tsdb.add("service.up", "support", now, 1.0)
    e.tsdb.add_sample(sample("support", cpu=75, mem=2000, latency_p95_ms=4000, error_rate=0.2, loop_lag_ms=400))
    for _ in range(2):
        asyncio.run(w.platform_tick())
    assert {"cpu:support", "mem:support", "slow:support", "err:support", "lag:support"} <= set(w.incidents)


def mock_cicd(runs, heals):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/internal/runs":
            return httpx.Response(200, json=runs)
        if request.url.path.endswith("/auto-heal"):
            heals.append(request.url.path.split("/")[-2])
            return httpx.Response(200, json={"id": heals[-1], "attempt": 1})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(id, status="failed", kind="transient", attempts=0, age=999):
    return {"id": id, "title": f"run {id}", "status": status, "created_at": time.time() - 500, "updated_at": time.time() - age, "heal_attempts": attempts,
            "heal": {"kind": kind, "diagnosis": "request timed out", "suggested_fix": "retry"} if status == "failed" else None, "stages": [], "attention": []}


async def tick(w, runs, heals):
    async with mock_cicd(runs, heals) as c:
        await w.delivery_tick(c)


def test_transient_failures_are_retried_automatically_but_code_failures_are_not():
    e, w = fresh_watch()
    heals = []
    asyncio.run(tick(w, [run("a", kind="transient"), run("b", kind="code"), run("c", kind="security")], heals))
    assert heals == ["a"]                                                         # only the transient one
    assert w.engine.heal_log[-1]["action"] == "needs_human" or any(h["action"] == "auto_rerun" for h in w.engine.heal_log)
    assert "run:b" in w.incidents and w.incidents["run:b"]["needs_user"]
    assert "run:c" in w.incidents and w.incidents["run:c"]["severity"] == "critical"
    assert "run:a" not in w.incidents


def test_auto_heal_stops_after_the_limit_and_hands_over_to_a_person():
    e, w = fresh_watch()
    heals = []
    asyncio.run(tick(w, [run("x", kind="transient", attempts=watch.MAX_AUTO_HEALS)], heals))
    assert heals == [] and w.incidents["run:x"]["needs_user"] and "retries" in w.incidents["run:x"]["title"].lower()


def test_auto_heal_backs_off_between_attempts():
    e, w = fresh_watch()
    heals = []
    asyncio.run(tick(w, [run("y", kind="transient", age=1)], heals))
    assert heals == []


def test_a_healed_run_is_logged_and_its_incident_resolved():
    e, w = fresh_watch()
    asyncio.run(tick(w, [run("z", status="succeeded", attempts=1)], []))
    assert any(h["action"] == "healed" and h["run_id"] == "z" for h in e.heal_log)
    assert e.cicd_runs[0]["status"] == "succeeded"


def mock_iac(stacks, check_results):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/iac/internal/stacks":
            return httpx.Response(200, json=stacks)
        if request.url.path.endswith("/drift-check"):
            sid = request.url.path.split("/")[-2]
            return httpx.Response(200, json={**next(s for s in stacks if s["id"] == sid), "drift": check_results[sid]})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def stack(id, title="Prod web"):
    return {"id": id, "title": title, "cloud": "Hetzner", "region": "fsn1", "resources": 3, "applied_at": time.time(), "drift": {"status": "unchecked", "findings": []}}


def test_drift_findings_become_incidents_that_need_the_admin_and_clear_when_fixed():
    e, w = fresh_watch()
    f = [{"resource": "hcloud_firewall.web", "summary": "rule added outside Terraform", "risk_score": 90, "auto_apply": False}]

    async def go(results):
        async with mock_iac([stack("s1")], {"s1": results}) as c:
            await w.drift_tick(c, force=True)

    asyncio.run(go({"status": "drift", "checked_at": time.time(), "findings": f}))
    assert e.drift_state["stacks"][0]["status"] == "drift" and w.incidents["drift:s1"]["severity"] == "critical" and w.incidents["drift:s1"]["needs_user"]
    asyncio.run(go({"status": "in_sync", "checked_at": time.time(), "findings": []}))
    assert "drift:s1" not in w.incidents
    asyncio.run(go({"status": "cannot_check", "checked_at": time.time(), "findings": [], "error": "Terraform is not installed", "how_to_fix": "Install Terraform"}))
    assert w.incidents["drift_unchecked:s1"]["how_to_fix"] == "Install Terraform"


def test_drift_monitor_reports_an_unreachable_iac_agent_without_crashing():
    e, w = fresh_watch()

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")))) as c:
            await w.drift_tick(c)

    asyncio.run(go())
    assert e.drift_state["error"] == "Infrastructure agent unreachable"


def test_cicd_metrics_are_derived_from_the_runs_seen():
    e = Engine()
    now = time.time()
    e.cicd_runs = [{"id": "1", "status": "succeeded", "created_at": now, "heal_attempts": 0, "stages": [{"duration_ms": 2000}]},
                   {"id": "2", "status": "failed", "created_at": now, "heal_attempts": 2, "stages": []}]
    q = lambda m, **k: asyncio.run(e.query(MetricQuery(metric=m, window="1h", **k)))  # noqa: E731
    assert q("cicd.success_rate")["value"] == 0.5 and q("cicd.failed_runs")["value"] == 1 and q("cicd.auto_heals")["value"] == 2
    assert q("cicd.runs", by="status")["value"] == {"succeeded": 1, "failed": 1}
    assert q("cicd.avg_duration_s")["value"] == 2.0
