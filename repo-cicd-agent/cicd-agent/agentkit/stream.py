"""
Streaming tool-calling loop used by the chat agents. Yields plain dict events the API layer forwards as SSE:

  {"type": "token", "text": ...}          visible reply text as it is generated
  {"type": "tool_start"|"tool_end", ...}  tool activity
  {"type": "ui", "ui": {...}}             generative-UI payload parsed from the model's <ui> element
  {"type": "done", "text": full_text, "usage": {...}}
"""

import asyncio
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from .uiblocks import UiSplitter, parse_ui


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return ""


async def stream_agent(
    llm, messages: List[BaseMessage], tools: Dict[str, Any], *, config: Optional[dict] = None, max_steps: int = 4
) -> AsyncIterator[Dict[str, Any]]:
    splitter = UiSplitter()
    full = ""
    usage = {"input_tokens": 0, "output_tokens": 0}
    started = time.perf_counter()
    first_token_ms: Optional[int] = None

    for _ in range(max_steps):
        acc = None
        async for chunk in llm.astream(messages, config=config):
            acc = chunk if acc is None else acc + chunk
            piece = _text(chunk.content)
            if piece:
                if first_token_ms is None:
                    first_token_ms = int((time.perf_counter() - started) * 1000)
                visible = splitter.feed(piece)
                if visible:
                    full += visible
                    yield {"type": "token", "text": visible}
        if acc is None:
            break
        um = getattr(acc, "usage_metadata", None) or {}
        usage["input_tokens"] += int(um.get("input_tokens", 0))
        usage["output_tokens"] += int(um.get("output_tokens", 0))
        calls = getattr(acc, "tool_calls", None) or []
        if not calls:
            break
        messages.append(acc if isinstance(acc, AIMessage) else AIMessage(content=_text(acc.content), tool_calls=calls))
        for call in calls:
            name, args = call["name"], call.get("args", {})
            yield {"type": "tool_start", "name": name, "args": args}
            tool = tools.get(name)
            try:
                result = "ERROR: unknown tool" if tool is None else await tool.ainvoke(args)
            except Exception as exc:  # a failing tool should not kill the reply
                result = f"ERROR: {type(exc).__name__}: {exc}"
            yield {"type": "tool_end", "name": name, "result": str(result)[:500]}
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    tail, raw = splitter.finish()
    if tail:
        full += tail
        yield {"type": "token", "text": tail}
    payload = parse_ui(raw) if raw else None
    if payload and (payload.blocks or payload.quick_replies or payload.mood != "calm"):
        yield {"type": "ui", "ui": payload.model_dump()}
    yield {
        "type": "done", "text": full.strip(), "usage": usage,
        "ttft_ms": first_token_ms, "total_ms": int((time.perf_counter() - started) * 1000),
        "ui": payload.model_dump() if payload else None,
    }
