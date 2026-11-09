import time

from app import runs

from .conftest import auth

TOKEN = {"X-Ingest-Token": "test-ingest"}


def failed_run(kind, attempts=0):
    r = runs.new_run("u1", f"{kind} failure", "d", "diff", "primary")
    r["status"], r["heal_attempts"] = "failed", attempts
    r["heal"] = {"kind": kind, "diagnosis": "d", "suggested_fix": "f"}
    return r


def test_failure_classifier_separates_transient_from_real_problems():
    c = runs.classify_failure
    assert c("tests", "ConnectionResetError: connection reset by peer") == "transient"
    assert c("build", "pull access: 503 Service Unavailable") == "transient"
    assert c("tests", "request timed out after 30s") == "transient"
    assert c("tests", "AssertionError: expected 3 got 4") == "code"
    assert c("tests", "FAILED tests/test_net.py::test_read_timeout - AssertionError: timed out was not raised") == "code"  # a test about timeouts is not a flaky network
    assert c("tests", "ReadTimeout: connection timed out") == "transient"
    assert c("build", "Dockerfile: no such file or directory") == "config"
    assert c("scan", "Secret scan on added lines: FAILED\n[secret] a.py:3 AWS access key") == "security"
    assert c("deploy", "something odd") == "unknown"


def test_internal_api_needs_the_service_token(client):
    assert client.get("/api/internal/runs").status_code == 401
    assert client.get("/api/internal/runs", headers={"X-Ingest-Token": "guess"}).status_code == 401
    assert client.get("/api/internal/runs", headers=auth()).status_code == 401  # an admin login is not the service token
    assert client.get("/api/internal/runs", headers=TOKEN).status_code == 200


def test_auto_heal_only_retries_transient_failures(client):
    r = failed_run("transient")
    resp = client.post(f"/api/internal/runs/{r['id']}/auto-heal", headers=TOKEN)
    assert resp.status_code == 200 and resp.json()["attempt"] == 1
    assert r["heal_attempts"] == 1 and r["status"] == "running" and r["heal_log"][-1]["action"] == "auto_rerun"
    for kind in ("code", "config", "security", "unknown"):
        other = failed_run(kind)
        assert client.post(f"/api/internal/runs/{other['id']}/auto-heal", headers=TOKEN).status_code == 409, kind
        assert other["status"] == "failed"  # untouched


def test_auto_heal_has_a_hard_limit(client):
    r = failed_run("transient", attempts=runs.MAX_AUTO_HEALS)
    assert client.post(f"/api/internal/runs/{r['id']}/auto-heal", headers=TOKEN).status_code == 409
    assert client.post("/api/internal/runs/nope/auto-heal", headers=TOKEN).status_code == 404
    assert client.post(f"/api/internal/runs/{r['id']}/auto-heal").status_code == 401


def test_failed_runs_tell_the_admin_exactly_what_to_do():
    r = failed_run("code")
    st = {"id": "tests", "label": "Tests"}
    runs._attention(r, st)
    assert r["attention"][0]["severity"] == "blocker" and r["attention"][0]["how_to_fix"] == "f"
    leak = failed_run("security")
    runs._attention(leak, st)
    assert "credential" in leak["attention"][0]["title"].lower() and leak["attention"][0]["persist"]
    exhausted = failed_run("transient", attempts=runs.MAX_AUTO_HEALS)
    runs._attention(exhausted, st)
    assert "keeps failing" in exhausted["attention"][0]["title"]
    pending = failed_run("transient", attempts=0)
    runs._attention(pending, st)
    assert pending["attention"] == []  # still being retried automatically: nothing for a person to do yet


def test_skipped_stages_are_explained_as_optional_steps():
    r = runs.new_run("u", "t", "d", "diff", "primary")
    for s in r["stages"]:
        s.update(status="skipped", log="not configured")
    runs._optional_notes(r)
    assert {a["title"] for a in r["attention"]} >= {"Tests was skipped", "Build image was skipped"} and all(a["severity"] == "info" for a in r["attention"])


def test_the_conversation_endpoint_is_admin_only(client):
    body = {"message": "hi"}
    assert client.post("/api/agent/chat", json=body).status_code == 401
    assert client.post("/api/agent/chat", json=body, headers={"Authorization": "Bearer dev:shopper@example.com"}).status_code == 403
    assert client.post("/api/agent/chat", json={"message": ""}, headers=auth()).status_code == 422
    assert client.post("/api/agent/chat", json={"message": "x", "model": "bogus"}, headers=auth()).status_code == 422
