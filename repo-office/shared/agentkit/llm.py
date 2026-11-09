"""
LLM access, all through OpenRouter: GPT 6.1 Sol (primary) and Claude Sonnet 5.5 (secondary), with automatic fallback
from one to the other. In `stub` mode a canned model stands in so our own stack can be load tested without spending
credits.
"""

import asyncio
import json
import time
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from .settings import get_settings

# USD per million tokens (input, output) from OpenRouter's catalogue; used when a response carries no cost.
PRICING = {
    "openai/gpt-6.1-sol": (2.0, 10.0),
    "anthropic/claude-sonnet-5.5": (2.0, 10.0),
    "google/gemini-3.5-flash": (1.5, 9.0),
}


def model_for(alias: str) -> str:
    s = get_settings()
    return {"primary": s.llm_primary_model, "secondary": s.llm_secondary_model}.get(alias, alias)


def available_models() -> List[Dict[str, str]]:
    s = get_settings()
    return [
        {"alias": "primary", "id": s.llm_primary_model, "label": "GPT 6.1 Sol"},
        {"alias": "secondary", "id": s.llm_secondary_model, "label": "Claude Sonnet 5.5"},
    ]


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICING.get(model, (2.0, 10.0))
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


class StubChatModel(BaseChatModel):
    """Deterministic stand-in. Replies with a short answer plus a generative-UI block, after a simulated delay."""

    latency_ms: int = 350

    @property
    def _llm_type(self) -> str:
        return "stub"

    def bind_tools(self, tools, **kwargs):  # tools are ignored: the stub never calls them
        return self

    def _reply(self, messages: List[BaseMessage]) -> str:
        last = next((m.content for m in reversed(messages) if m.type == "human"), "")
        ui = {"mood": "calm", "blocks": [{"type": "card", "title": "Stub reply", "body": "Simulated answer for load testing.", "tone": "info"}],
              "quick_replies": ["Tell me more", "Thanks"]}
        return f"Thanks for your message about {str(last)[:60]!r}. This is a simulated reply. <ui>{json.dumps(ui)}</ui>"

    def _generate(self, messages, stop=None, run_manager: Optional[CallbackManagerForLLMRun] = None, **kw) -> ChatResult:
        time.sleep(self.latency_ms / 1000)
        text = self._reply(messages)
        msg = AIMessage(content=text, usage_metadata={"input_tokens": 40, "output_tokens": max(1, len(text) // 4), "total_tokens": 40 + len(text) // 4})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kw) -> ChatResult:
        await asyncio.sleep(self.latency_ms / 1000)
        return self._sync_result(messages)

    def _sync_result(self, messages) -> ChatResult:
        text = self._reply(messages)
        msg = AIMessage(content=text, usage_metadata={"input_tokens": 40, "output_tokens": max(1, len(text) // 4), "total_tokens": 40 + len(text) // 4})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _astream(self, messages, stop=None, run_manager=None, **kw) -> AsyncIterator[ChatGenerationChunk]:
        text = self._reply(messages)
        await asyncio.sleep(self.latency_ms / 2000)
        words = text.split(" ")
        for i, w in enumerate(words):
            await asyncio.sleep(self.latency_ms / 2000 / max(1, len(words)))
            last = i == len(words) - 1
            chunk = AIMessageChunk(content=w + ("" if last else " "))
            if last:
                chunk.usage_metadata = {"input_tokens": 40, "output_tokens": max(1, len(text) // 4), "total_tokens": 40 + len(text) // 4}
            yield ChatGenerationChunk(message=chunk)


def get_chat_model(alias: str = "primary", *, temperature: float = 0.2, streaming: bool = False, agent: str = "agent",
                   fallback: bool = True, tools: Optional[list] = None):
    """A chat model for `alias` ('primary', 'secondary' or a raw OpenRouter id), with telemetry attached.
    `tools` are bound to every model in the chain so tool calling survives a fallback."""
    from langchain_openai import ChatOpenAI

    from .telemetry import TelemetryCallback

    s = get_settings()
    if s.llm_mode == "stub":
        return StubChatModel(latency_ms=s.stub_latency_ms)
    if not s.openrouter_api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    def build(model_id: str):
        return ChatOpenAI(
            model=model_id, base_url=s.openrouter_base_url, api_key=s.openrouter_api_key, temperature=temperature,
            streaming=streaming, timeout=90, max_retries=1,
            default_headers={"HTTP-Referer": "http://localhost", "X-Title": f"Agent Office / {agent}"},
            stream_usage=True, callbacks=[TelemetryCallback(agent=agent, model=model_id)],
        )

    def ready(model_id: str):
        m = build(model_id)
        return m.bind_tools(tools) if tools else m

    main_id = model_for(alias)
    llm = ready(main_id)
    if fallback and alias in ("primary", "secondary"):
        other = model_for("secondary" if alias == "primary" else "primary")
        if other != main_id:
            return llm.with_fallbacks([ready(other)])
    return llm
