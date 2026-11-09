from fastapi.testclient import TestClient

from hub.main import app

ADMIN = {"Authorization": "Bearer dev:admin@example.com"}
CUSTOMER = {"Authorization": "Bearer dev:shopper@example.com"}
TOKEN = {"X-Ingest-Token": "office-test-token"}
EVENT = {"team": "support", "member": "agent", "kind": "message", "text": "hello"}
client = TestClient(app)


def test_office_is_for_the_admin_only():
    assert client.get("/roster").status_code == 401
    assert client.get("/roster", headers=CUSTOMER).status_code == 403
    assert client.get("/events", headers=CUSTOMER).status_code == 403
    assert client.post("/demo/start", headers=CUSTOMER).status_code == 403
    r = client.get("/roster", headers=ADMIN)
    assert r.status_code == 200 and {t["id"] for t in r.json()["teams"]} == {"iac", "support", "cicd", "observability"}


def test_only_our_services_can_write_to_the_floor():
    assert client.post("/events", json=EVENT).status_code == 401
    assert client.post("/events", json=EVENT, headers={"X-Ingest-Token": "guess"}).status_code == 401
    assert client.post("/events", json=EVENT, headers=ADMIN).status_code == 401  # even the admin's login is not the service token
    assert client.post("/events", json=EVENT, headers=TOKEN).status_code == 200
    assert client.post("/events", json={**EVENT, "member": "ghost"}, headers=TOKEN).status_code == 422


def test_live_stream_needs_an_admin_token():
    assert client.get("/stream").status_code == 401
    assert client.get("/stream?access_token=dev:shopper@example.com").status_code == 403
    assert client.get("/stream?access_token=nonsense").status_code == 401


def test_sign_in_config_and_role_endpoint_are_available_to_the_gate():
    cfg = client.get("/api/config").json()
    assert cfg["auth_mode"] == "dev" and cfg["dev_admin_email"] == "admin@example.com"
    assert client.get("/api/me", headers=ADMIN).json()["is_admin"] is True
    assert client.get("/api/me", headers=CUSTOMER).json()["is_admin"] is False


def test_the_office_page_loads_the_gate_first():
    html = client.get("/").text
    assert "gate.js" in html and 'src="office.js"' not in html  # office.js is injected only after an admin signs in
