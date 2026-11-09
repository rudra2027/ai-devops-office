"""
AI dashboard designer. It first decides whether it has what it needs; if not it asks ALL its questions at once (never a
trickle of one question at a time). Once it has enough it designs a dashboard from the metric catalog. Anything it invents
that is not in the catalog is rejected and fed back so it corrects itself.
"""

import json
from typing import Any, Dict, List, Literal, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from agentkit.llm import get_chat_model
from agentkit.tracing import run_config

from .dashboards import Dashboard, validate_dashboard
from .engine import CATALOG, Engine


class Question(BaseModel):
    text: str
    options: List[str] = Field(default_factory=list, description="2 to 5 suggested answers the person can click")


class DesignerReply(BaseModel):
    """Your answer. Use mode 'ask' to get missing information first, or 'dashboard' once you can design it."""

    mode: Literal["ask", "dashboard"]
    message: str = Field(..., description="One or two friendly sentences to the person")
    questions: List[Question] = Field(default_factory=list, max_length=4, description="mode=ask: ALL the questions you need answered, at once")
    dashboard: Optional[Dashboard] = Field(None, description="mode=dashboard: the full dashboard")


def system_prompt() -> str:
    cat = [{"key": m.key, "label": m.label, "unit": m.unit, "group": m.group, "what": m.description, "by": m.by, "default_agg": m.default_agg} for m in CATALOG.values()]
    return f"""You are an observability engineer who designs monitoring dashboards for a platform made of these services: support (customer chat), iac (infrastructure agent), cicd (CI/CD agent), office (visualization), observability (this service). Metrics are limited to this catalog; you may NOT use any other metric name:
{json.dumps(cat)}

Windows: 15m, 1h, 6h, 24h, 7d (infrastructure metrics keep only the last 6h). Aggregations: avg, max, min, sum, last, p50, p95, p99, rate. `by` splits a metric by one of its labels; `where` keeps one label value, e.g. {{"service": "support"}}.

How to work:
1. If the request leaves out something that changes the design (what to monitor, which services, the time range, who reads it, what 'bad' means), do NOT guess. Reply with mode=ask and ALL your questions in one go (at most 4, each with 2 to 5 clickable options). Never ask something the person already told you.
2. When you have enough, reply with mode=dashboard. Choose the best widget for each question: gauge for a value against a limit, stat for a headline number, timeseries for change over time, bar for comparing services or models, table to compare several metrics per service, status for up/down. Set warn/crit thresholds that make sense for the metric. Put the most important widgets first. Use 4 to 12 widgets. Widths are out of 4 columns.
3. If a dashboard is already open, change it rather than starting over.
Always answer by calling the DesignerReply tool."""


async def design(engine: Engine, messages: List[Dict[str, str]], current: Optional[Dict[str, Any]], alias: str = "primary") -> Dict[str, Any]:
    llm = get_chat_model(alias, temperature=0.2, agent="observability", fallback=False, tools=[DesignerReply])
    sys = system_prompt()
    if current:
        sys += f"\n\nThe dashboard currently open (modify it as asked):\n{json.dumps(current)}"
    convo: List[Any] = [SystemMessage(content=sys)]
    for m in messages[-12:]:
        convo.append(HumanMessage(content=m["content"]) if m["role"] == "user" else AIMessage(content=m["content"]))
    last_err = ""
    for attempt in range(3):
        out = await llm.ainvoke(convo, config=run_config("observability", task="dashboard-design"))
        calls = getattr(out, "tool_calls", None) or []
        if not calls:
            return {"mode": "ask", "message": str(out.content)[:600] or "Could you tell me a bit more about what you want to monitor?", "questions": [], "dashboard": None}
        try:
            reply = DesignerReply.model_validate(calls[0]["args"])
        except Exception as exc:
            last_err = f"Your reply was invalid: {exc}"
            convo += [out, ToolMessage(content=last_err, tool_call_id=calls[0]["id"])]
            continue
        if reply.mode == "ask":
            if not reply.questions:
                last_err = "mode=ask needs at least one question."
            else:
                return reply.model_dump()
        elif reply.dashboard is None:
            last_err = "mode=dashboard needs a dashboard."
        else:
            errs = validate_dashboard(reply.dashboard, engine)
            if not errs:
                return reply.model_dump()
            last_err = "These problems must be fixed (use only catalog metrics):\n- " + "\n- ".join(errs)
        convo += [out, ToolMessage(content=last_err, tool_call_id=calls[0]["id"])]
    raise RuntimeError(f"The designer could not produce a valid dashboard: {last_err[:300]}")
