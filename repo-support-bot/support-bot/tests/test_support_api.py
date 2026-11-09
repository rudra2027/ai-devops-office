import json

from agentkit.cache import get_cache

from .conftest import auth


def events(resp):
    return [json.loads(l[5:]) for l in resp.text.splitlines() if l.startswith("data:")]


def test_health_and_public_config_expose_no_secrets(client):
    assert client.get("/health").json()["status"] == "ok"
    cfg = client.get("/api/config").json()
    assert "openrouter" not in json.dumps(cfg).lower() and "api_key" not in cfg
    assert [m["alias"] for m in cfg["models"]] == ["primary", "secondary"]


def test_every_api_route_requires_sign_in(client):
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    assert client.get("/api/conversations").status_code == 401
    assert client.post("/api/stt", files={"audio": ("a.wav", b"x", "audio/wav")}).status_code == 401
    assert client.post("/api/chat", json={"message": "hi"}, headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_chat_streams_tokens_then_ui_then_done_and_persists(client):
    r = client.post("/api/chat", json={"message": "Where is my order 4412?"}, headers=auth())
    assert r.status_code == 200
    ev = events(r)
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "meta" and kinds[-1] == "done" and "token" in kinds and "ui" in kinds
    assert "<ui>" not in "".join(e.get("text", "") for e in ev)  # the ui element is never shown as text
    done = ev[-1]
    assert done["ui"]["blocks"][0]["type"] == "card"

    cid = ev[0]["conversation_id"]
    convs = client.get("/api/conversations", headers=auth()).json()
    assert cid in [c["id"] for c in convs]
    msgs = client.get(f"/api/conversations/{cid}", headers=auth()).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["ui"]["quick_replies"]


def test_conversations_are_private_to_their_owner(client):
    cid = events(client.post("/api/chat", json={"message": "my private question"}, headers=auth("alice@example.com")))[0]["conversation_id"]
    bob = auth("bob@example.com")
    assert cid not in [c["id"] for c in client.get("/api/conversations", headers=bob).json()]
    assert client.get(f"/api/conversations/{cid}", headers=bob).status_code == 404
    assert client.delete(f"/api/conversations/{cid}", headers=bob).status_code == 404
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": cid}, headers=bob).status_code == 404
    assert client.get(f"/api/conversations/{cid}", headers=auth("alice@example.com")).status_code == 200


def test_input_validation(client):
    h = auth()
    assert client.post("/api/chat", json={"message": ""}, headers=h).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 4001}, headers=h).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "model": "gpt-9000"}, headers=h).status_code == 422
    assert client.post("/api/stt", files={"audio": ("a.wav", b"", "audio/wav")}, headers=h).status_code == 422
    assert client.post("/api/stt", files={"audio": ("a.wav", b"x" * (8 * 1024 * 1024 + 1), "audio/wav")}, headers=h).status_code == 413


def test_html_in_messages_is_stored_verbatim_not_executed(client):
    cid = events(client.post("/api/chat", json={"message": "<script>alert(1)</script>"}, headers=auth()))[0]["conversation_id"]
    msgs = client.get(f"/api/conversations/{cid}", headers=auth()).json()["messages"]
    assert msgs[0]["content"] == "<script>alert(1)</script>"  # the UI escapes on render (Kit.md); the API keeps data intact


def test_chat_rate_limit_per_user(client, monkeypatch):
    from app import main

    monkeypatch.setattr(main, "rate_limited", lambda key, limit, window=60: True)
    r = client.post("/api/chat", json={"message": "hi"}, headers=auth("carol@example.com"))
    assert r.status_code == 429


def test_delete_conversation_removes_messages(client):
    cid = events(client.post("/api/chat", json={"message": "to be deleted"}, headers=auth("dave@example.com")))[0]["conversation_id"]
    assert client.delete(f"/api/conversations/{cid}", headers=auth("dave@example.com")).status_code == 200
    assert client.get(f"/api/conversations/{cid}", headers=auth("dave@example.com")).status_code == 404


def test_stt_stub_returns_text(client):
    r = client.post("/api/stt", files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")}, headers=auth())
    assert r.status_code == 200 and "text" in r.json()


def test_demo_orders_seeded_for_the_fallback_store(client):
    import asyncio

    rows = asyncio.run(client.app.state.store.select("orders", {"id": "4412"}, order=None))
    assert rows and rows[0]["status"] == "processing"


def test_frontend_is_served_without_caching(client):
    r = client.get("/")
    assert r.status_code == 200 and "no-cache" in r.headers.get("cache-control", "")


def test_me_reports_the_role(client):
    assert client.get("/api/me", headers=auth("shopper@example.com")).json()["is_admin"] is False
    assert client.get("/api/me", headers=auth("admin@example.com")).json()["is_admin"] is True
    assert client.get("/api/me").status_code == 401


def test_customers_are_always_served_by_the_default_model_but_the_admin_can_choose(client):
    models = client.get("/api/config").json()["models"]
    cust = events(client.post("/api/chat", json={"message": "hi", "model": "secondary"}, headers=auth("shopper@example.com")))[0]
    adm = events(client.post("/api/chat", json={"message": "hi", "model": "secondary"}, headers=auth("admin@example.com")))[0]
    assert cust["model"] == models[0]["id"] and adm["model"] == models[1]["id"]


def test_ticket_inbox_is_admin_only(client):
    assert client.get("/api/admin/tickets", headers=auth("shopper@example.com")).status_code == 403
    assert client.get("/api/admin/tickets").status_code == 401
    assert isinstance(client.get("/api/admin/tickets", headers=auth("admin@example.com")).json(), list)
