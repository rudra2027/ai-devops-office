"""
A conversational agent endpoint any service can mount:  POST /api/agent/chat  (admin only, streamed as server-sent events).

The client sends the conversation so far, so the endpoint itself keeps no state. Events are the same as the support chat:
meta, token, tool_start, tool_end, ui, done, error. The agent can only act through the tools its service gives it.
"""

import json
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from . import office as office_mod
from .auth import AuthUser, require_admin
from .cache import rate_limited
from .llm import get_chat_model, model_for
from .stream import stream_agent
from .tracing import run_config


class Turn(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=6000)


class AgentChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: List[Turn] = Field(default_factory=list, max_length=30)
    model: str = "primary"


def _sse(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


def register_agent_chat(app, *, agent: str, team: str, voice: str, system_prompt: Callable[[AuthUser], str],
                        tools: Callable[[AuthUser, Request, List[Dict[str, str]]], Dict[str, Any]],
                        tool_voice: Optional[Callable[[str], str]] = None) -> None:
    """`voice` is the colleague who speaks for the team in the Agent Office; `tool_voice` maps a tool to the colleague who runs it."""
    office = office_mod.Team(team)

    @app.post("/api/agent/chat")
    async def agent_chat(req: AgentChatRequest, request: Request, user: AuthUser = Depends(require_admin)):
        if req.model not in ("primary", "secondary"):
            raise HTTPException(422, "Unknown model")
        if rate_limited(f"agentchat:{agent}:{user.id}", 20):
            raise HTTPException(429, "Slow down a little: too many messages in a minute.")
        history = [t.model_dump() for t in req.history]
        tool_map = tools(user, request, history + [{"role": "user", "content": req.message}])
        messages: List[Any] = [SystemMessage(content=system_prompt(user))]
        messages += [HumanMessage(content=t["content"]) if t["role"] == "user" else AIMessage(content=t["content"]) for t in history[-20:]]
        messages.append(HumanMessage(content=req.message))
        llm = get_chat_model(req.model, agent=agent, streaming=True, tools=list(tool_map.values()))

        async def events():
            yield _sse({"type": "meta", "model": model_for(req.model)})
            office(voice, "inbound", f"You: {req.message}"[:300], state="working")
            final = None
            try:
                async for ev in stream_agent(llm, messages, tool_map, config=run_config(agent, kind="office-chat")):
                    if ev["type"] == "tool_start":
                        who = (tool_voice(ev["name"]) if tool_voice else voice) or voice
                        if who != voice:
                            office(voice, "handoff", f"Asking {who} for {ev['name']}.", to_member=who, state="idle")
                        office(who, "tool_call", f"{ev['name']}({json.dumps(ev['args'], default=str)[:110]})", state="working")
                    elif ev["type"] == "tool_end":
                        who = (tool_voice(ev["name"]) if tool_voice else voice) or voice
                        office(who, "tool_result", ev["result"][:180], state="idle")
                    elif ev["type"] == "done":
                        final = ev
                    yield _sse(ev)
            except Exception as exc:
                office(voice, "error", f"{type(exc).__name__}: {exc}"[:240])
                yield _sse({"type": "error", "message": "I hit a problem answering that. Please try again."})
                return
            if final:
                office(voice, "message", final["text"][:320], state="waiting" if "Needs you" in final["text"] or "?" in final["text"][-200:] else "idle")

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
