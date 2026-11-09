import subprocess
import time
from pathlib import Path

from app import stages
from app.review import deterministic_findings

from .conftest import auth

CLEAN = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"
LEAK = 'diff --git a/c.py b/c.py\n--- a/c.py\n+++ b/c.py\n@@ -1,1 +1,2 @@\n x = 1\n+AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n'


def wait(client, rid, states, headers, limit=20):
    t = time.time()
    while time.time() - t < limit:
        r = client.get(f"/api/runs/{rid}", headers=headers).json()
        if r["status"] in states:
            return r
        time.sleep(0.1)
    raise AssertionError(f"run stayed {r['status']}")


def test_requires_sign_in(client):
    assert client.get("/api/runs").status_code == 401
    assert client.post("/api/runs", json={"diff": CLEAN}).status_code == 401


def test_clean_change_goes_through_approval_and_runs_stages(client):
    h = auth()
    rid = client.post("/api/runs", json={"diff": CLEAN, "title": "tiny"}, headers=h).json()["id"]
    r = wait(client, rid, {"awaiting_approval"}, h)
    assert r["review"]["recommend_approval"] and r["approved_by"] is None
    assert client.post(f"/api/runs/{rid}/approve", json={}, headers=h).status_code == 200
    r = wait(client, rid, {"succeeded", "failed"}, h)
    by = {s["id"]: s["status"] for s in r["stages"]}
    assert by["scan"] == "passed" and by["tests"] == "skipped" and by["deploy"] == "skipped"  # honest about what could not run
    assert r["approved_by"] == "alice@example.com"


def test_nothing_runs_before_approval_and_double_approval_is_refused(client):
    h = auth()
    rid = client.post("/api/runs", json={"diff": CLEAN}, headers=h).json()["id"]
    r = wait(client, rid, {"awaiting_approval"}, h)
    assert all(s["status"] == "pending" for s in r["stages"])
    assert client.post(f"/api/runs/{rid}/approve", json={}, headers=h).status_code == 200
    assert client.post(f"/api/runs/{rid}/approve", json={}, headers=h).status_code == 409
    assert client.post(f"/api/runs/{rid}/reject", headers=h).status_code == 409


def test_leaked_secret_cannot_be_approved_even_with_override(client):
    h = auth()
    rid = client.post("/api/runs", json={"diff": LEAK}, headers=h).json()["id"]
    r = wait(client, rid, {"awaiting_approval"}, h)
    assert not r["review"]["recommend_approval"] and r["review"]["risk"] == "high"
    resp = client.post(f"/api/runs/{rid}/approve", json={"override_warnings": True}, headers=h)
    assert resp.status_code == 409 and "cannot be overridden" in resp.json()["detail"]
    assert client.post(f"/api/runs/{rid}/reject", headers=h).json()["status"] == "rejected"


CUSTOMER = {"Authorization": "Bearer dev:shopper@example.com"}


def test_customers_are_locked_out(client):
    rid = client.post("/api/runs", json={"diff": CLEAN}, headers=auth()).json()["id"]
    assert client.get("/api/runs", headers=CUSTOMER).status_code == 403
    assert client.post("/api/runs", json={"diff": CLEAN}, headers=CUSTOMER).status_code == 403
    assert client.get(f"/api/runs/{rid}", headers=CUSTOMER).status_code == 403
    assert client.post(f"/api/runs/{rid}/approve", json={}, headers=CUSTOMER).status_code == 403
    assert client.delete(f"/api/runs/{rid}", headers=CUSTOMER).status_code == 403
    assert client.get("/api/samples", headers=CUSTOMER).status_code == 403


def test_webhook_starts_a_background_review_that_still_needs_approval(client, tmp_path, monkeypatch):
    from agentkit.settings import get_settings
    from app import main

    repo = tmp_path / "proj"
    repo.mkdir()

    def git(*a):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    (repo / "a.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-qm", "one")
    (repo / "a.py").write_text("x = 1\ny = 2\n")
    git("commit", "-qam", "two")
    monkeypatch.setattr(main, "ROOTS", [tmp_path.resolve()])
    body = {"repo_path": str(repo), "base": "HEAD~1", "head": "HEAD"}

    assert client.post("/api/webhook/change", json=body).status_code == 404  # disabled until a token is configured
    monkeypatch.setattr(get_settings(), "cicd_webhook_token", "hook-secret")
    assert client.post("/api/webhook/change", json=body).status_code == 401
    assert client.post("/api/webhook/change", json=body, headers={"X-Webhook-Token": "wrong"}).status_code == 401
    r = client.post("/api/webhook/change", json=body, headers={"X-Webhook-Token": "hook-secret"})
    assert r.status_code == 202
    run = wait(client, r.json()["id"], {"awaiting_approval"}, auth())  # visible to the admin, waiting for a human
    assert run["source"] == "repo" and all(s["status"] == "pending" for s in run["stages"])
    outside = client.post("/api/webhook/change", json={"repo_path": str(tmp_path.parent)}, headers={"X-Webhook-Token": "hook-secret"})
    assert outside.status_code in (400, 403)


def test_input_validation(client):
    h = auth()
    assert client.post("/api/runs", json={}, headers=h).status_code == 422
    assert client.post("/api/runs", json={"diff": "   "}, headers=h).status_code == 400
    assert client.post("/api/runs", json={"sample_id": "nope"}, headers=h).status_code == 404
    assert client.post("/api/runs", json={"diff": CLEAN, "model": "x"}, headers=h).status_code == 422
    assert client.post("/api/runs", json={"diff": "x" * 200_001}, headers=h).status_code == 422


def test_repo_path_outside_allowed_roots_is_forbidden(client):
    r = client.post("/api/runs", json={"repo_path": "C:\\Windows" if Path("C:\\Windows").exists() else "/etc"}, headers=auth())
    assert r.status_code == 403


def test_git_refs_cannot_inject_options(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    for bad in ("--output=/tmp/x", "-p", "a b", "x;rm -rf"):
        try:
            stages.git_diff(tmp_path, bad, "HEAD")
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")


def test_secret_scan_reports_file_and_line():
    f = deterministic_findings(LEAK)
    assert f and f[0].severity == "blocker" and f[0].file == "c.py" and f[0].line == 2
    assert deterministic_findings(CLEAN) == []


def test_build_and_deploy_are_skipped_unless_configured(monkeypatch):
    monkeypatch.delenv("CICD_ENABLE_DOCKER", raising=False)
    monkeypatch.delenv("ARGOCD_SERVER", raising=False)
    assert stages.run_build(None, "t")[0] == "skipped"
    assert stages.run_deploy("t")[0] == "skipped"


def test_samples_listed(client):
    assert {s["id"] for s in client.get("/api/samples", headers=auth()).json()} == {"clean-refactor", "sql-injection", "secret-leak"}
