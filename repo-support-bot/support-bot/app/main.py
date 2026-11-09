"""
Support agent API. Streaming chat (SSE) with tool calling and generative-UI payloads, Supabase auth, per-user rate
limiting, persisted conversations, and Gemini speech-to-text. Speech output happens in the browser.
"""

import json
import time
from pathlib import Path
from typing import Optional

from fastapi import Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agentkit import office as office_mod
from agentkit.app import create_service_app, mount_frontend
from agentkit.auth import AuthUser, require_admin, require_user
from agentkit.cache import rate_limited
from agentkit.llm import get_chat_model, model_for
from agentkit.settings import get_settings
from agentkit.store import now_iso
from agentkit.stream import stream_agent
from agentkit.tracing import run_config

from .prompts import system_prompt
from .stt import transcribe
from .tools import build_tools

AGENT = "support"
TABLES = ["conversations", "messages", "orders", "tickets"]
MAX_MESSAGE = 4000
MAX_AUDIO = 8 * 1024 * 1024

office = office_mod.Team("support")

DEMO_ORDERS = [
    {"id": "4412", "status": "processing", "eta": "tomorrow", "items": ["Noise-cancelling headphones"]},
    {"id": "5120", "status": "shipped", "eta": "in 2 days", "items": ["Standing desk", "Cable tray"]},
    {"id": "7788", "status": "delivered", "eta": "delivered yesterday", "items": ["USB-C hub"]},
    {"id": "9001", "status": "delayed", "eta": "next week", "items": ["Ergonomic chair"]},
]


async def _seed_demo_orders(app) -> None:
    """Supabase gets these from the SQL migration; the local SQLite fallback needs them seeded."""
    store = app.state.store
    if store.backend == "sqlite" and not await store.select("orders", limit=1):
        for o in DEMO_ORDERS:
            await store.insert("orders", {**o, "user_id": None})


app = create_service_app(title="Support Agent", agent=AGENT, tables=TABLES, features=["chat", "stt", "tts-browser"], startup=[_seed_demo_orders])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE)
    conversation_id: Optional[str] = None
    model: str = "primary"


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


@app.get("/api/conversations")
async def list_conversations(user: AuthUser = Depends(require_user)):
    rows = await app.state.store.select("conversations", {"user_id": user.id, "agent": AGENT}, order="updated_at", limit=60, token=user.token)
    return [{"id": r["id"], "title": r.get("title") or "New chat", "updated_at": r.get("updated_at") or r.get("created_at"), "model": r.get("model")} for r in rows]


async def _owned(conv_id: str, user: AuthUser):
    rows = await app.state.store.select("conversations", {"id": conv_id, "user_id": user.id}, order=None, limit=1, token=user.token)
    if not rows:
        raise HTTPException(404, "Conversation not found")
    return rows[0]


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str, user: AuthUser = Depends(require_user)):
    conv = await _owned(conv_id, user)
    msgs = await app.state.store.select("messages", {"conversation_id": conv_id}, order="created_at", desc=False, limit=500, token=user.token)
    return {"conversation": conv, "messages": [{"id": m["id"], "role": m["role"], "content": m["content"], "ui": m.get("ui"), "meta": m.get("meta"), "created_at": m.get("created_at")} for m in msgs]}


@app.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: AuthUser = Depends(require_user)):
    await _owned(conv_id, user)
    await app.state.store.delete("messages", {"conversation_id": conv_id}, token=user.token)
    await app.state.store.delete("conversations", {"id": conv_id}, token=user.token)
    return {"deleted": conv_id}


@app.post("/api/chat")
async def chat(req: ChatRequest, user: AuthUser = Depends(require_user)):
    s = get_settings()
    if rate_limited(f"chat:{user.id}", s.rate_limit_per_minute):
        raise HTTPException(429, "You're sending messages very quickly. Give it a moment and try again.")
    if req.model not in ("primary", "secondary"):
        raise HTTPException(422, "Unknown model")
    alias = req.model if user.is_admin else "primary"  # customers always get the default model; only the admin chooses
    store = app.state.store

    if req.conversation_id:
        conv = await _owned(req.conversation_id, user)
    else:
        conv = await store.insert("conversations", {
            "user_id": user.id, "agent": AGENT, "title": req.message.strip()[:60], "model": model_for(alias), "updated_at": now_iso(),
        }, token=user.token)
    history = await store.select("messages", {"conversation_id": conv["id"]}, order="created_at", desc=False, limit=40, token=user.token)
    await store.insert("messages", {"conversation_id": conv["id"], "user_id": user.id, "role": "user", "content": req.message}, token=user.token)

    name = (user.email or "there").split("@")[0]
    messages = [SystemMessage(content=system_prompt(name))]
    for m in history[-16:]:
        messages.append(HumanMessage(content=m["content"]) if m["role"] == "user" else AIMessage(content=m["content"]))
    messages.append(HumanMessage(content=req.message))

    tools = build_tools(store, user)
    llm = get_chat_model(alias, agent=AGENT, streaming=True, tools=list(tools.values()))

    async def events():
        yield _sse({"type": "meta", "conversation_id": conv["id"], "model": model_for(alias), "title": conv.get("title")})
        office("desk", "inbound", f"Customer: {req.message}"[:300], state="working")
        office("desk", "handoff", "Passing the call to Nia.", state="idle", to_member="agent")
        office("agent", "thinking", "Reading the message...", state="working")
        final = None
        started = time.perf_counter()
        try:
            async for ev in stream_agent(llm, messages, tools, config=run_config(AGENT, conversation=conv["id"], user=user.id)):
                if ev["type"] == "tool_start":
                    office("agent", "handoff", f"Need {ev['name']}.", to_member="tools")
                    office("tools", "tool_call", f"{ev['name']}({json.dumps(ev['args'])[:120]})", state="working")
                elif ev["type"] == "tool_end":
                    office("tools", "tool_result", ev["result"][:200], state="idle")
                    office("tools", "handoff", "Result back to Nia.", to_member="agent")
                if ev["type"] == "done":
                    final = ev
                yield _sse(ev)
        except Exception as exc:
            office("agent", "error", f"{type(exc).__name__}: {exc}"[:300])
            yield _sse({"type": "error", "message": "The assistant hit a problem. Please try again."})
            return
        if final:
            await store.insert("messages", {
                "conversation_id": conv["id"], "user_id": user.id, "role": "assistant", "content": final["text"], "ui": final.get("ui"),
                "meta": {"model": model_for(alias), "usage": final["usage"], "total_ms": final["total_ms"], "ttft_ms": final["ttft_ms"]},
            }, token=user.token)
            await store.update("conversations", {"id": conv["id"]}, {"model": model_for(alias)}, token=user.token)
            office("agent", "message", final["text"][:300], state="idle")
            office("agent", "handoff", "Reply is ready, Vera can voice it.", to_member="voice")
            office("voice", "done", "Reply delivered to the customer.", state="idle")

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/admin/tickets")
async def admin_tickets(user: AuthUser = Depends(require_admin)):
    """Tickets customers asked the bot to open, newest first."""
    rows = await app.state.store.select("tickets", order="created_at", limit=100, token=user.token)
    return [{k: r.get(k) for k in ("id", "subject", "details", "priority", "status", "created_at", "user_id")} for r in rows]


@app.post("/api/stt")
async def stt(audio: UploadFile = File(...), user: AuthUser = Depends(require_user)):
    if rate_limited(f"stt:{user.id}", 12):
        raise HTTPException(429, "Too many voice messages. Try again in a moment.")
    data = await audio.read()
    if not data:
        raise HTTPException(422, "Empty audio")
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "Audio is too long (max 8 MB)")
    office("voice", "tool_call", "Transcribing with Gemini 3.5 Flash...", state="working")
    text = await transcribe(data, audio.content_type or "")
    office("voice", "tool_result", text[:160] or "(no speech)", state="idle")
    return {"text": text}


mount_frontend(app, str(Path(__file__).resolve().parent.parent / "frontend"))
