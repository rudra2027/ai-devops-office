from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import evals
from app.main import app
from app.metrics import pct, summarize

TOKEN = {"X-Ingest-Token": "test-token"}


def auth(email="alice@example.com"):
    return {"Authorization": f"Bearer dev:{email}"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def call(**kw):
    return {"agent": "support", "model": "openai/gpt-6.1-sol", "latency_ms": 1000, "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01, **kw}


def test_percentile_math():
    assert pct([], 0.5) == 0
    assert pct([10], 0.95) == 10
    assert pct(list(range(1, 101)), 0.5) == 50.5
    assert round(pct(list(range(1, 101)), 0.95), 2) == 95.05


def test_summarize_groups_and_windows():
    now = datetime.now(timezone.utc)
    iso = lambda m: (now - timedelta(minutes=m)).isoformat()  # noqa: E731
    rows = [
        {**call(latency_ms=100), "created_at": iso(5), "status": "ok"},
        {**call(latency_ms=300), "created_at": iso(10), "status": "ok"},
        {**call(latency_ms=900, agent="iac", model="anthropic/claude-sonnet-5.5"), "created_at": iso(20), "status": "error", "error": "boom"},
        {**call(), "created_at": iso(600), "status": "ok"},  # outside the 1h window
    ]
    s = summarize(rows, "1h", now)
    assert s["totals"]["requests"] == 3 and s["totals"]["errors"] == 1
    assert s["agents"]["support"]["requests"] == 2 and s["agents"]["iac"]["error_rate"] == 1.0
    assert set(s["models"]) == {"openai/gpt-6.1-sol", "anthropic/claude-sonnet-5.5"}
    assert sum(b["requests"] for b in s["series"]) == 3 and len(s["series"]) == 12
    assert s["recent_errors"][0]["error"] == "boom"
    assert summarize(rows, "24h", now)["totals"]["requests"] == 4


def test_ingest_needs_the_token(client):
    assert client.post("/api/ingest", json=call()).status_code == 401
    assert client.post("/api/ingest", json=call(), headers={"X-Ingest-Token": "nope"}).status_code == 401
    assert client.post("/api/ingest", json=call(), headers=TOKEN).json() == {"accepted": 1}


def test_ingest_validates_and_bounds_input(client):
    assert client.post("/api/ingest", json=call(latency_ms=-5), headers=TOKEN).status_code == 422
    assert client.post("/api/ingest", json={"model": "m"}, headers=TOKEN).status_code == 422
    assert client.post("/api/ingest", json=[call() for _ in range(201)], headers=TOKEN).status_code == 413
    assert client.post("/api/ingest", json=[call(), call(agent="cicd", status="error", error="x")], headers=TOKEN).json() == {"accepted": 2}


def test_dashboard_routes_require_sign_in(client):
    for path in ("/api/overview", "/api/langsmith", "/api/evals/suites", "/api/evals/history", "/api/services", "/api/loadtests"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/evals/run", json={"suite": "support_quality"}).status_code == 401


def test_overview_reflects_ingested_calls_and_validates_window(client):
    client.post("/api/ingest", json=[call(agent="support", latency_ms=200), call(agent="support", latency_ms=400, status="error", error="timeout")], headers=TOKEN)
    import time

    time.sleep(2.2)  # overview is cached for 2 s
    d = client.get("/api/overview?window=1h", headers=auth()).json()
    assert d["totals"]["requests"] >= 4 and "support" in d["agents"] and d["totals"]["errors"] >= 1
    assert client.get("/api/overview?window=99y", headers=auth()).status_code == 422


def test_eval_endpoint_validation(client):
    h = auth()
    assert client.post("/api/evals/run", json={"suite": "nope"}, headers=h).status_code == 404
    assert client.post("/api/evals/run", json={"suite": "support_quality", "models": ["gpt-evil"]}, headers=h).status_code == 422
    assert client.post("/api/evals/run", json={"suite": "support_quality", "models": []}, headers=h).status_code == 422
    assert client.get("/api/evals/runs/unknown", headers=h).status_code == 404
    names = {s["id"] for s in client.get("/api/evals/suites", headers=h).json()}
    assert names == {"support_quality", "iac_requirements", "cicd_review"}


def test_eval_summary_math():
    run = {"id": "r", "suite": "s", "status": "done", "total": 3, "done": 3, "started": 0, "models": [], "results": [
        {"model": "a", "passed": True, "score": 0.9, "latency_ms": 100}, {"model": "a", "passed": False, "score": 0.5, "latency_ms": 300},
        {"model": "b", "passed": True, "score": 1.0, "latency_ms": 200}]}
    m = evals.summarize_run(run)["models"]
    assert m["a"] == {"cases": 2, "pass_rate": 0.5, "avg_score": 0.7, "avg_latency_ms": 200}
    assert m["b"]["pass_rate"] == 1.0


def test_every_eval_case_has_a_rubric():
    for suite, cases in evals.SUITES.items():
        assert cases and all(c.rubric and c.prompt and c.system for c in cases), suite


def test_customers_cannot_read_agent_performance_data(client):
    cust = {"Authorization": "Bearer dev:shopper@example.com"}
    for path in ("/api/overview", "/api/langsmith", "/api/evals/suites", "/api/evals/history", "/api/services", "/api/loadtests"):
        assert client.get(path, headers=cust).status_code == 403, path
    assert client.post("/api/evals/run", json={"suite": "support_quality"}, headers=cust).status_code == 403
    assert client.post("/api/ingest", json=call(), headers=TOKEN).status_code == 200  # services still report with the token
