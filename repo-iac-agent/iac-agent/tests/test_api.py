import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from api import sessions
from api.main import app
from app.provisioner import pipeline
from app.provisioner.schemas import GeneratedStack, SessionStatus, TerraformFile


def auth(email="alice@example.com"):
    return {"Authorization": f"Bearer dev:{email}"}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def new(client, who="alice@example.com"):
    return client.post("/iac/sessions", json={}, headers=auth(who)).json()


def test_every_route_requires_sign_in(client):
    assert client.get("/iac/sessions").status_code == 401
    assert client.post("/iac/sessions").status_code == 401
    assert client.get("/iac/examples").status_code == 401
    assert client.get("/ops/findings").status_code == 401


def test_examples_cover_several_clouds(client):
    clouds = {e["cloud"] for e in client.get("/iac/examples", headers=auth()).json()}
    assert {"Hetzner", "AWS", "Azure", "Google Cloud"} <= clouds


CUSTOMER = {"Authorization": "Bearer dev:shopper@example.com"}


def test_customers_cannot_reach_any_admin_route(client):
    sid = new(client)["id"]
    for method, path in [("get", "/iac/sessions"), ("post", "/iac/sessions"), ("get", f"/iac/sessions/{sid}"), ("delete", f"/iac/sessions/{sid}"),
                         ("post", f"/iac/sessions/{sid}/plan"), ("post", f"/iac/sessions/{sid}/approve"), ("post", f"/iac/sessions/{sid}/apply"),
                         ("get", f"/iac/sessions/{sid}/download"), ("get", "/iac/examples"), ("get", "/ops/findings")]:
        assert getattr(client, method)(path, headers=CUSTOMER).status_code == 403, path
    assert client.post(f"/iac/sessions/{sid}/messages", json={"content": "hi"}, headers=CUSTOMER).status_code == 403


def test_session_lifecycle(client):
    s = new(client)
    sid = s["id"]
    assert s["status"] == "collecting" and s["files"] == []
    assert sid in [x["id"] for x in client.get("/iac/sessions", headers=auth()).json()]
    assert client.delete(f"/iac/sessions/{sid}", headers=auth()).status_code == 200
    assert client.get(f"/iac/sessions/{sid}", headers=auth()).status_code == 404


def test_message_validation(client):
    sid = new(client)["id"]
    h = auth()
    assert client.post(f"/iac/sessions/{sid}/messages", json={"content": ""}, headers=h).status_code == 422
    assert client.post(f"/iac/sessions/{sid}/messages", json={"content": "x" * 4001}, headers=h).status_code == 422
    assert client.post(f"/iac/sessions/{sid}/messages", json={"content": "hi", "model": "bogus"}, headers=h).status_code == 422


def test_a_model_that_never_submits_fails_gracefully_and_is_reported(client):
    sid = new(client)["id"]
    h = auth()
    assert client.post(f"/iac/sessions/{sid}/messages", json={"content": "a vm on hetzner"}, headers=h).status_code == 202
    for _ in range(100):
        s = client.get(f"/iac/sessions/{sid}", headers=h).json()
        if not s["busy"]:
            break
        time.sleep(0.1)
    assert s["status"] == "failed" and "without submitting" in s["error"]
    assert s["history"][-1]["role"] == "agent"
    assert s["title"] == "a vm on hetzner"


def test_second_message_while_busy_is_refused(client):
    sid = new(client)["id"]
    sessions._live[sid].busy = True
    r = client.post(f"/iac/sessions/{sid}/messages", json={"content": "again"}, headers=auth())
    assert r.status_code == 409
    sessions._live[sid].busy = False


def test_plan_approve_apply_gates(client):
    sid = new(client)["id"]
    h = auth()
    assert client.post(f"/iac/sessions/{sid}/plan", headers=h).status_code == 400      # nothing designed yet
    assert client.post(f"/iac/sessions/{sid}/approve", headers=h).status_code == 400   # nothing planned
    assert client.post(f"/iac/sessions/{sid}/apply", headers=h).status_code == 400     # not approved


def test_apply_needs_an_approved_plan_even_if_status_is_forced(client):
    sid = new(client)["id"]
    s = sessions._live[sid]
    s.status = SessionStatus.planned  # a human has not approved yet
    assert client.post(f"/iac/sessions/{sid}/apply", headers=auth()).status_code == 400
    assert client.post(f"/iac/sessions/{sid}/approve", headers=auth()).status_code == 200
    assert client.get(f"/iac/sessions/{sid}", headers=auth()).json()["approved_by"] == "alice@example.com"


def test_download_zip_and_persistence_across_restart(client):
    sid = new(client)["id"]
    h = auth()
    assert client.get(f"/iac/sessions/{sid}/download", headers=h).status_code == 404
    s = sessions._live[sid]
    s.stack = GeneratedStack(files=[TerraformFile(path="main.tf", content='resource "a" "b" {}')], summary="one resource")
    s.title = "kept"
    client.post(f"/iac/sessions/{sid}/approve", headers=h)  # any state change persists the snapshot
    z = client.get(f"/iac/sessions/{sid}/download", headers=h)
    assert z.status_code == 200 and zipfile.ZipFile(io.BytesIO(z.content)).read("main.tf") == b'resource "a" "b" {}'
    sessions._live.clear()
    pipeline._sessions.clear()  # simulate a server restart: state must come back from the store
    again = client.get(f"/iac/sessions/{sid}", headers=h).json()
    assert again["id"] == sid and [f["path"] for f in again["files"]] == ["main.tf"]
    assert client.get(f"/iac/sessions/{sid}", headers=CUSTOMER).status_code == 403


def test_findings_agent_endpoints_need_the_agent_token_when_set(client, monkeypatch):
    from api import secrets

    monkeypatch.setattr(secrets.secrets, "agent_api_token", "s3cret")
    body = {"resource": "aws_x.y", "summary": "s", "risk_score": 50}
    assert client.post("/ops/findings", json=body).status_code == 401
    assert client.post("/ops/findings", json=body, headers={"X-Agent-Token": "wrong"}).status_code == 401
    f = client.post("/ops/findings", json=body, headers={"X-Agent-Token": "s3cret"}).json()
    assert f["status"] == "pending_approval"
    assert client.post(f"/ops/findings/{f['id']}/approve", headers=auth()).json()["status"] == "approved"
    assert client.post(f"/ops/findings/{f['id']}/reject", headers=auth()).status_code == 409  # already decided
