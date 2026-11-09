"""Dashboard specs: validated JSON built only from catalog metrics, plus the built-in dashboards."""

import time
import uuid
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .engine import CATALOG, Engine, MetricQuery


class Widget(BaseModel):
    type: Literal["stat", "timeseries", "bar", "gauge", "table", "status"] = Field(
        ..., description="stat: one big number with a sparkline. timeseries: lines over time (may combine several queries). bar: latest value per label. "
        "gauge: a value against warn/crit thresholds. table: one row per label, one column per query. status: services up/down.")
    title: str = Field(..., max_length=60)
    queries: List[MetricQuery] = Field(default_factory=list, max_length=6, description="1 to 6 queries. status widgets need none.")
    width: int = Field(2, ge=1, le=4, description="grid columns out of 4")
    warn: Optional[float] = Field(None, description="value at which the widget turns amber")
    crit: Optional[float] = Field(None, description="value at which the widget turns red")
    max: Optional[float] = Field(None, description="gauge scale maximum, e.g. 100 for percentages")
    note: str = Field("", max_length=140, description="why this widget is here, in one line")


class Dashboard(BaseModel):
    title: str = Field(..., max_length=60)
    description: str = Field("", max_length=240)
    widgets: List[Widget] = Field(..., min_length=1, max_length=16)


def validate_dashboard(d: Dashboard, engine: Engine) -> List[str]:
    """Every problem, so the designer can fix them all in one go."""
    errs: List[str] = []
    for i, w in enumerate(d.widgets, 1):
        if w.type != "status" and not w.queries:
            errs.append(f"Widget {i} '{w.title}': a {w.type} widget needs at least one query")
        if w.type in ("stat", "gauge", "bar") and len(w.queries) > 1:
            errs.append(f"Widget {i} '{w.title}': a {w.type} widget uses exactly one query (use a table or timeseries to combine metrics)")
        for q in w.queries:
            e = engine.validate(q)
            if e:
                errs.append(f"Widget {i} '{w.title}': {e}")
    return errs


def _w(type, title, metric, window="1h", by=None, agg=None, width=2, **kw) -> Dict[str, Any]:
    return {"type": type, "title": title, "queries": [{"metric": metric, "window": window, "by": by, "agg": agg}], "width": width, **kw}


BUILTIN: List[Dict[str, Any]] = [
    {"id": "builtin-platform", "title": "Platform health", "builtin": True, "description": "Is everything up, and how hard are the machine and each service working?", "widgets": [
        {"type": "status", "title": "Services", "queries": [], "width": 2},
        _w("gauge", "Availability (1h)", "platform.availability", width=1, warn=99, crit=95, max=100),
        _w("gauge", "Machine CPU", "host.cpu_percent", "15m", width=1, warn=70, crit=90, max=100),
        _w("gauge", "Machine memory", "host.memory_percent", "15m", width=1, warn=80, crit=92, max=100),
        _w("timeseries", "CPU by service (% of machine)", "service.cpu_percent", "1h", by="service", width=2),
        _w("timeseries", "Memory by service (MB)", "service.memory_mb", "1h", by="service", width=2),
        _w("timeseries", "Throughput (req/s)", "service.rps", "1h", by="service", width=2),
        _w("timeseries", "Latency p95 (ms)", "service.latency_p95_ms", "1h", by="service", width=2, warn=1000, crit=3000),
        _w("bar", "Error rate by service", "service.error_rate", "1h", by="service", width=2, warn=0.01, crit=0.05),
        _w("bar", "Event-loop lag (ms)", "service.loop_lag_ms", "1h", by="service", width=2, warn=100, crit=250),
    ]},
    {"id": "builtin-llm", "title": "LLM & cost", "builtin": True, "description": "Model calls, speed, failures and spend per agent and model.", "widgets": [
        _w("stat", "Calls (24h)", "llm.requests", "24h", width=1), _w("stat", "Spend (24h)", "llm.cost_usd", "24h", width=1),
        _w("stat", "Latency p95", "llm.latency_ms", "24h", width=1), _w("gauge", "Error rate", "llm.error_rate", "24h", width=1, warn=0.02, crit=0.1, max=1),
        _w("timeseries", "Calls by model", "llm.requests", "24h", by="model", width=2), _w("timeseries", "Latency p95 by model (ms)", "llm.latency_ms", "24h", by="model", width=2),
        _w("bar", "Spend by agent (USD)", "llm.cost_usd", "24h", by="agent", width=2), _w("bar", "Tokens by model", "llm.tokens", "24h", by="model", width=2),
    ]},
    {"id": "builtin-delivery", "title": "Delivery (CI/CD)", "builtin": True, "description": "Pipeline health and how often the platform healed itself.", "widgets": [
        _w("gauge", "Success rate (7d)", "cicd.success_rate", "7d", width=1, warn=0.9, crit=0.7, max=1), _w("stat", "Runs (7d)", "cicd.runs", "7d", width=1),
        _w("stat", "Failed (7d)", "cicd.failed_runs", "7d", width=1, warn=1, crit=3), _w("stat", "Auto-heal retries", "cicd.auto_heals", "7d", width=1),
        _w("bar", "Runs by status", "cicd.runs", "7d", by="status", width=2), _w("stat", "Average pipeline duration (s)", "cicd.avg_duration_s", "7d", width=2),
    ]},
    {"id": "builtin-drift", "title": "Infrastructure drift", "builtin": True, "description": "Do the clouds still match the code the Infrastructure agent wrote?", "widgets": [
        _w("stat", "Stacks monitored", "drift.stacks_monitored", "1h", width=1), _w("stat", "In sync", "drift.stacks_in_sync", "1h", width=1),
        _w("stat", "Open findings", "drift.open_findings", "1h", width=2, warn=1, crit=5),
    ]},
]


def new_id() -> str:
    return "d-" + uuid.uuid4().hex[:8]


def to_row(d: Dashboard, did: Optional[str] = None) -> Dict[str, Any]:
    now = time.time()
    return {"id": did or new_id(), "title": d.title, "spec": d.model_dump(), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now))}
