"""
Observability engine: time-series store, metric catalog and query engine.

The catalog is the single vocabulary shared by the built-in dashboards, the dashboard designer (which may only use
metrics listed here) and the chat. Metrics come from five sources:

  tsdb      samples pushed by every service (CPU, memory, APM) and by this service (host, health probes)
  llm       every model call reported by the agents
  cicd      pipeline runs read from the CI/CD service
  drift     infrastructure drift checks
  platform  derived: availability and services up
"""

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

WINDOWS = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}
AGGS = ["avg", "max", "min", "sum", "last", "p50", "p95", "p99", "rate"]
RETENTION_S = 6 * 3600


class Metric(BaseModel):
    key: str
    label: str
    unit: str
    description: str
    source: str
    group: str
    by: List[str] = Field(default_factory=list, description="labels it can be split by")
    default_agg: str = "avg"
    good: Optional[str] = Field(None, description="'low' if lower is better, 'high' if higher is better")


def M(key, label, unit, description, source, group, by, agg="avg", good=None) -> Metric:
    return Metric(key=key, label=label, unit=unit, description=description, source=source, group=group, by=by, default_agg=agg, good=good)


_S = ["service"]
CATALOG: Dict[str, Metric] = {m.key: m for m in [
    # ---- infrastructure: the machine and each process
    M("host.cpu_percent", "Host CPU", "%", "CPU used across the whole machine", "tsdb", "Infrastructure", [], "avg", "low"),
    M("host.memory_percent", "Host memory", "%", "Memory in use on the machine", "tsdb", "Infrastructure", [], "avg", "low"),
    M("host.disk_percent", "Host disk", "%", "Disk space used on the system drive", "tsdb", "Infrastructure", [], "last", "low"),
    M("service.cpu_percent", "Service CPU", "%", "Share of the machine a service process uses", "tsdb", "Infrastructure", _S, "avg", "low"),
    M("service.memory_mb", "Service memory", "MB", "Resident memory of a service process", "tsdb", "Infrastructure", _S, "avg", "low"),
    M("service.threads", "Service threads", "", "OS threads in a service process", "tsdb", "Infrastructure", _S, "avg"),
    M("service.handles", "Open handles", "", "Open file/socket handles (leak detector)", "tsdb", "Infrastructure", _S, "max", "low"),
    # ---- APM: golden signals
    M("service.rps", "Throughput", "req/s", "Requests handled per second", "tsdb", "APM", _S, "avg"),
    M("service.requests", "Requests", "", "Requests handled", "tsdb", "APM", _S, "sum"),
    M("service.latency_p50_ms", "Latency p50", "ms", "Median request handling time", "tsdb", "APM", _S, "avg", "low"),
    M("service.latency_p95_ms", "Latency p95", "ms", "95th percentile request handling time", "tsdb", "APM", _S, "avg", "low"),
    M("service.latency_p99_ms", "Latency p99", "ms", "99th percentile request handling time", "tsdb", "APM", _S, "max", "low"),
    M("service.error_rate", "Error rate", "ratio", "Share of requests that failed with a 5xx", "tsdb", "APM", _S, "avg", "low"),
    M("service.inflight", "In-flight requests", "", "Requests being handled right now (saturation)", "tsdb", "APM", _S, "max", "low"),
    M("service.loop_lag_ms", "Event-loop lag", "ms", "How late the async loop runs: a blocked service shows up here first", "tsdb", "APM", _S, "max", "low"),
    M("service.up", "Service up", "", "1 when the health probe succeeds, 0 when it fails", "tsdb", "APM", _S, "avg", "high"),
    M("service.health_ms", "Health probe time", "ms", "Time the /health endpoint took to answer", "tsdb", "APM", _S, "avg", "low"),
    # ---- LLM: the cost and quality of the models
    M("llm.requests", "LLM calls", "", "Model calls", "llm", "LLM", ["agent", "model"], "sum"),
    M("llm.latency_ms", "LLM latency", "ms", "Time per model call", "llm", "LLM", ["agent", "model"], "p95", "low"),
    M("llm.error_rate", "LLM error rate", "ratio", "Share of model calls that failed", "llm", "LLM", ["agent", "model"], "avg", "low"),
    M("llm.tokens", "Tokens", "", "Input plus output tokens", "llm", "LLM", ["agent", "model"], "sum"),
    M("llm.cost_usd", "LLM spend", "USD", "Money spent on model calls", "llm", "LLM", ["agent", "model"], "sum", "low"),
    # ---- delivery: CI/CD health
    M("cicd.runs", "Pipeline runs", "", "Runs started", "cicd", "Delivery", ["status"], "sum"),
    M("cicd.success_rate", "Pipeline success rate", "ratio", "Finished runs that succeeded", "cicd", "Delivery", [], "avg", "high"),
    M("cicd.failed_runs", "Failed runs", "", "Runs that failed", "cicd", "Delivery", [], "sum", "low"),
    M("cicd.auto_heals", "Auto-heal retries", "", "Times the platform re-ran a failed pipeline on its own", "cicd", "Delivery", [], "sum"),
    M("cicd.avg_duration_s", "Pipeline duration", "s", "Average time the stages of a run took", "cicd", "Delivery", [], "avg", "low"),
    # ---- infrastructure drift
    M("drift.stacks_monitored", "Stacks monitored", "", "Applied stacks the platform keeps checking", "drift", "Drift", [], "last"),
    M("drift.stacks_in_sync", "Stacks in sync", "", "Stacks whose real state matches the code", "drift", "Drift", [], "last", "high"),
    M("drift.open_findings", "Open drift findings", "", "Differences between code and reality awaiting a decision", "drift", "Drift", [], "last", "low"),
    # ---- platform
    M("platform.services_up", "Services up", "", "How many services answer their health check", "platform", "Platform", [], "last", "high"),
    M("platform.availability", "Availability", "%", "Share of health probes that succeeded", "platform", "Platform", _S, "avg", "high"),
]}

SAMPLE_FIELDS = {  # field in a pushed sample -> metric
    "cpu_percent": "service.cpu_percent", "memory_mb": "service.memory_mb", "threads": "service.threads", "handles": "service.handles",
    "rps": "service.rps", "requests": "service.requests", "latency_p50_ms": "service.latency_p50_ms", "latency_p95_ms": "service.latency_p95_ms",
    "latency_p99_ms": "service.latency_p99_ms", "error_rate": "service.error_rate", "inflight": "service.inflight", "loop_lag_ms": "service.loop_lag_ms",
}


class MetricQuery(BaseModel):
    metric: str
    agg: Optional[str] = None
    window: str = "1h"
    by: Optional[str] = Field(None, description="split by a label, e.g. 'service', 'agent' or 'model'")
    where: Dict[str, str] = Field(default_factory=dict, description="keep only these label values, e.g. {'service': 'support'}")


def _pct(vals: List[float], p: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def reduce(vals: List[float], agg: str, seconds: float = 1.0) -> Optional[float]:
    if not vals:
        return None
    if agg == "avg":
        return sum(vals) / len(vals)
    if agg == "max":
        return max(vals)
    if agg == "min":
        return min(vals)
    if agg == "sum":
        return sum(vals)
    if agg == "last":
        return vals[-1]
    if agg == "rate":
        return sum(vals) / max(1.0, seconds)
    return _pct(vals, {"p50": 0.5, "p95": 0.95, "p99": 0.99}[agg])


class TSDB:
    """In-memory ring of recent samples per (metric, label)."""

    def __init__(self) -> None:
        self.series: Dict[Tuple[str, str], Deque[Tuple[float, float]]] = defaultdict(deque)
        self.latest_sample: Dict[str, Dict[str, Any]] = {}

    def add(self, metric: str, label: str, ts: float, value: float) -> None:
        d = self.series[(metric, label)]
        d.append((ts, float(value)))
        cutoff = ts - RETENTION_S
        while d and d[0][0] < cutoff:
            d.popleft()

    def add_sample(self, s: Dict[str, Any]) -> None:
        svc, ts = s["service"], float(s.get("ts") or time.time())
        for field, metric in SAMPLE_FIELDS.items():
            if field in s and s[field] is not None:
                self.add(metric, svc, ts, s[field])
        self.latest_sample[svc] = s

    def labels(self, metric: str) -> List[str]:
        return sorted(l for (m, l) in self.series if m == metric)

    def points(self, metric: str, label: str, since: float) -> List[Tuple[float, float]]:
        return [p for p in self.series.get((metric, label), ()) if p[0] >= since]


def _bucket(points: List[Tuple[float, float]], since: float, now: float, step: float, agg: str) -> List[List[float]]:
    buckets: Dict[int, List[float]] = defaultdict(list)
    for ts, v in points:
        buckets[int((ts - since) // step)].append(v)
    out = []
    for i in sorted(buckets):
        r = reduce(buckets[i], "sum" if agg == "rate" else agg, step)
        if agg == "rate" and r is not None:
            r = r / step
        out.append([round(since + (i + 0.5) * step, 1), round(r, 4)])
    return out


class Engine:
    def __init__(self) -> None:
        self.tsdb = TSDB()
        self.pending: List[Dict[str, Any]] = []        # samples not yet persisted
        self.llm_rows: Callable[[], Awaitable[List[Dict[str, Any]]]] = self._none
        self.cicd_runs: List[Dict[str, Any]] = []       # refreshed by the delivery monitor
        self.drift_state: Dict[str, Any] = {"stacks": []}  # refreshed by the drift monitor
        self.heal_log: List[Dict[str, Any]] = []
        self.delivery_error: Optional[str] = None

    @staticmethod
    async def _none() -> List[Dict[str, Any]]:
        return []

    # ---- ingestion
    def ingest_sample(self, s: Dict[str, Any]) -> None:
        self.tsdb.add_sample(s)
        self.pending.append(s)

    # ---- querying
    def describe(self) -> List[Dict[str, Any]]:
        return [m.model_dump() for m in CATALOG.values()]

    def validate(self, q: MetricQuery) -> Optional[str]:
        m = CATALOG.get(q.metric)
        if not m:
            return f"Unknown metric '{q.metric}'. Valid metrics: {', '.join(CATALOG)}"
        if q.window not in WINDOWS:
            return f"Unknown window '{q.window}'. Use one of {', '.join(WINDOWS)}"
        if q.agg and q.agg not in AGGS:
            return f"Unknown aggregation '{q.agg}'. Use one of {', '.join(AGGS)}"
        if q.by and q.by not in m.by:
            return f"'{q.metric}' cannot be split by '{q.by}' (allowed: {m.by or 'nothing'})"
        for k in q.where:
            if k not in m.by:
                return f"'{q.metric}' cannot be filtered by '{k}' (allowed: {m.by or 'nothing'})"
        return None

    async def query(self, q: MetricQuery) -> Dict[str, Any]:
        err = self.validate(q)
        if err:
            raise ValueError(err)
        m = CATALOG[q.metric]
        agg = q.agg or m.default_agg
        secs = WINDOWS[q.window]
        now = time.time()
        since = now - secs
        step = max(10.0, secs / 60)
        src = {"tsdb": self._q_tsdb, "llm": self._q_llm, "cicd": self._q_cicd, "drift": self._q_drift, "platform": self._q_platform}[m.source]
        series, value = await src(q, m, agg, since, now, step)
        return {"metric": q.metric, "label": m.label, "unit": m.unit, "group": m.group, "good": m.good, "agg": agg, "window": q.window,
                "series": series, "value": value, "by": q.by, "ts": now}

    async def _q_tsdb(self, q, m, agg, since, now, step):
        labels = self.tsdb.labels(q.metric)
        if "service" in q.where:
            labels = [l for l in labels if l == q.where["service"]]
        per, merged = {}, []
        series = []
        for label in labels:
            pts = self.tsdb.points(q.metric, label, since)
            if not pts:
                continue
            per[label] = reduce([v for _, v in pts], agg, now - since)
            series.append({"name": label, "points": _bucket(pts, since, now, step, agg)})
            merged += pts
        if q.by:
            return series, per
        if not per:
            return [], None
        if len(series) > 1 and q.metric.startswith("service."):
            # several services and no split: combine into one line (sum for additive metrics, average otherwise)
            additive = m.default_agg == "sum" or q.metric in ("service.rps", "service.requests", "service.inflight")
            by_t: Dict[float, List[float]] = defaultdict(list)
            for s in series:
                for t, v in s["points"]:
                    by_t[t].append(v)
            comb = [[t, round(sum(vs) if additive else sum(vs) / len(vs), 4)] for t, vs in sorted(by_t.items())]
            vals = list(per.values())
            return [{"name": "all services", "points": comb}], (sum(vals) if additive else sum(vals) / len(vals))
        return series, reduce([v for _, v in merged], agg, now - since)

    async def _q_llm(self, q, m, agg, since, now, step):
        rows = [r for r in await self.llm_rows() if _ts(r["created_at"]) >= since]
        for k, v in q.where.items():
            rows = [r for r in rows if r.get(k) == v]
        key = q.by
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[r.get(key) if key else "all"].append(r)

        def val(r) -> float:
            return {"llm.requests": 1.0, "llm.latency_ms": float(r.get("latency_ms") or 0), "llm.error_rate": 0.0 if r.get("status") == "ok" else 1.0,
                    "llm.tokens": float((r.get("input_tokens") or 0) + (r.get("output_tokens") or 0)), "llm.cost_usd": float(r.get("cost_usd") or 0)}[q.metric]

        series, per = [], {}
        for g, rs in groups.items():
            pts = [(_ts(r["created_at"]), val(r)) for r in rs]
            per[g] = reduce([v for _, v in pts], agg, now - since)
            series.append({"name": g, "points": _bucket(pts, since, now, step, "sum" if q.metric == "llm.requests" and agg == "sum" else agg)})
        return series, (per if key else per.get("all"))

    async def _q_cicd(self, q, m, agg, since, now, step):
        runs = [r for r in self.cicd_runs if (r.get("created_at") or 0) >= since]
        finished = [r for r in runs if r["status"] in ("succeeded", "failed")]
        if q.metric == "cicd.runs":
            if q.by == "status":
                c: Dict[str, int] = defaultdict(int)
                for r in runs:
                    c[r["status"]] += 1
                return [], dict(c)
            return [{"name": "runs", "points": _bucket([(r["created_at"], 1.0) for r in runs], since, now, step, "sum")}], float(len(runs))
        if q.metric == "cicd.failed_runs":
            f = [r for r in runs if r["status"] == "failed"]
            return [{"name": "failed", "points": _bucket([(r["created_at"], 1.0) for r in f], since, now, step, "sum")}], float(len(f))
        if q.metric == "cicd.success_rate":
            return [], (sum(1 for r in finished if r["status"] == "succeeded") / len(finished)) if finished else None
        if q.metric == "cicd.auto_heals":
            return [], float(sum(int(r.get("heal_attempts") or 0) for r in runs))
        d = [x for x in (sum((s.get("duration_ms") or 0) for s in r.get("stages", [])) / 1000 for r in finished) if x > 0]  # runs without timings are not 0-second runs
        return [], (sum(d) / len(d)) if d else None

    async def _q_drift(self, q, m, agg, since, now, step):
        st = self.drift_state.get("stacks", [])
        return [], {"drift.stacks_monitored": float(len(st)), "drift.stacks_in_sync": float(sum(1 for s in st if s["status"] == "in_sync")),
                    "drift.open_findings": float(sum(len(s.get("findings", [])) for s in st))}[q.metric]

    async def _q_platform(self, q, m, agg, since, now, step):
        if q.metric == "platform.services_up":
            ups = [self.tsdb.points("service.up", l, now - 60) for l in self.tsdb.labels("service.up")]
            return [], float(sum(1 for p in ups if p and p[-1][1] >= 1))
        per, series = {}, []
        for label in self.tsdb.labels("service.up"):
            if q.where.get("service") and q.where["service"] != label:
                continue
            pts = self.tsdb.points("service.up", label, since)
            if pts:
                per[label] = 100 * sum(v for _, v in pts) / len(pts)
                series.append({"name": label, "points": _bucket([(t, v * 100) for t, v in pts], since, now, step, "avg")})
        if q.by:
            return series, per
        return [], (sum(per.values()) / len(per)) if per else None

    # ---- convenience for the platform dashboard
    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        out = {}
        for svc in self.tsdb.labels("service.up"):
            def last(metric):
                p = self.tsdb.points(metric, svc, now - 120)
                return p[-1][1] if p else None
            up = last("service.up")
            up = None if up is None else up
            sample = self.tsdb.latest_sample.get(svc, {})
            out[svc] = {"up": (None if up is None else bool(up)), "health_ms": last("service.health_ms"), "cpu_percent": last("service.cpu_percent"), "memory_mb": last("service.memory_mb"),
                        "rps": last("service.rps"), "latency_p95_ms": last("service.latency_p95_ms"), "error_rate": last("service.error_rate"),
                        "loop_lag_ms": last("service.loop_lag_ms"), "threads": last("service.threads"), "uptime_s": sample.get("uptime_s"),
                        "top_routes": sample.get("top_routes", []), "sample_age_s": round(now - sample["ts"]) if sample.get("ts") else None}
        host = {k: (self.tsdb.points(f"host.{k}", "host", now - 120) or [(0, None)])[-1][1] for k in ("cpu_percent", "memory_percent", "disk_percent")}
        return {"services": out, "host": host}


def _ts(v: Any) -> float:
    from .metrics import parse_ts

    return parse_ts(v).timestamp()
