"""
Every LLM call is measured (latency, tokens, cost, status) and reported to the observability service, which owns the
`llm_calls` table and powers the performance panel. Reporting is fire-and-forget on a background thread: if the
observability service is down, records are dropped rather than slowing a user's request.
"""

import json
import logging
import queue
import threading
import time
import urllib.request
from typing import Any, Dict, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from .llm import estimate_cost
from .settings import get_settings

log = logging.getLogger("agentkit.telemetry")

_q: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=5000)
_started = False
_lock = threading.Lock()
LOCAL_SINK = None  # set by the observability service itself so it can record without HTTP


def _worker() -> None:
    while True:
        rec = _q.get()
        s = get_settings()
        try:
            req = urllib.request.Request(
                f"{s.obs_url.rstrip('/')}/api/ingest",
                data=json.dumps(rec).encode(),
                headers={"Content-Type": "application/json", "X-Ingest-Token": s.ingest_token},
            )
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass


def record_call(rec: Dict[str, Any]) -> None:
    if LOCAL_SINK is not None:
        LOCAL_SINK(rec)
        return
    global _started
    if not get_settings().obs_url:
        return
    with _lock:
        if not _started:
            threading.Thread(target=_worker, daemon=True).start()
            _started = True
    try:
        _q.put_nowait(rec)
    except queue.Full:
        pass


class TelemetryCallback(BaseCallbackHandler):
    """Attach to a chat model; emits one record per completed or failed LLM call."""

    raise_error = False

    def __init__(self, agent: str, model: str) -> None:
        self.agent, self.model = agent, model
        self._t: Dict[UUID, float] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id: UUID, **kw: Any) -> None:
        self._t[run_id] = time.perf_counter()

    def on_llm_start(self, serialized, prompts, *, run_id: UUID, **kw: Any) -> None:
        self._t.setdefault(run_id, time.perf_counter())

    def _finish(self, run_id: UUID, status: str, usage: Dict[str, Any], error: Optional[str] = None) -> None:
        t0 = self._t.pop(run_id, None)
        if t0 is None:
            return
        it = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        ot = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        cost = usage.get("cost")
        record_call({
            "agent": self.agent, "model": self.model, "status": status, "error": (error or "")[:300] or None,
            "latency_ms": int((time.perf_counter() - t0) * 1000), "input_tokens": it, "output_tokens": ot,
            "cost_usd": float(cost) if cost is not None else estimate_cost(self.model, it, ot),
            "trace_id": str(run_id),
        })

    def on_llm_end(self, response, *, run_id: UUID, **kw: Any) -> None:
        usage: Dict[str, Any] = {}
        try:
            g = response.generations[0][0]
            um = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
            usage.update(um)
            tu = (response.llm_output or {}).get("token_usage") or {}
            for k, v in tu.items():
                usage.setdefault(k, v)
            rm = getattr(getattr(g, "message", None), "response_metadata", None) or {}
            for k, v in (rm.get("token_usage") or {}).items():
                usage.setdefault(k, v)
        except Exception:
            pass
        self._finish(run_id, "ok", usage)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        self._finish(run_id, "error", {}, f"{type(error).__name__}: {error}")
