"""Aggregations over recorded LLM calls: per agent, per model, and time series."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

WINDOWS = {"1h": (3600, 12), "24h": (86400, 24), "7d": (604800, 7)}


def parse_ts(s: Any) -> datetime:
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def pct(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _group(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    lat = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    errors = sum(1 for r in rows if r.get("status") != "ok")
    n = len(rows)
    return {
        "requests": n, "errors": errors, "error_rate": (errors / n) if n else 0.0,
        "p50_ms": round(pct(lat, 0.5)), "p95_ms": round(pct(lat, 0.95)), "p99_ms": round(pct(lat, 0.99)),
        "avg_ms": round(sum(lat) / len(lat)) if lat else 0,
        "input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in rows), 6),
    }


def summarize(rows: List[Dict[str, Any]], window: str = "1h", now: datetime = None) -> Dict[str, Any]:
    secs, nb = WINDOWS.get(window, WINDOWS["1h"])
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=secs)
    rows = [r for r in rows if parse_ts(r["created_at"]) >= cutoff]

    by_agent, by_model = defaultdict(list), defaultdict(list)
    for r in rows:
        by_agent[r["agent"]].append(r)
        by_model[r["model"]].append(r)

    step = secs / nb
    buckets: List[List[Dict[str, Any]]] = [[] for _ in range(nb)]
    for r in rows:
        i = min(nb - 1, int((parse_ts(r["created_at"]) - cutoff).total_seconds() // step))
        buckets[max(0, i)].append(r)
    fmt = "%H:%M" if window != "7d" else "%a"
    series = []
    for i, b in enumerate(buckets):
        t = cutoff + timedelta(seconds=step * (i + 1))
        g = _group(b)
        series.append({"label": t.astimezone().strftime(fmt), **{k: g[k] for k in ("requests", "errors", "p95_ms", "cost_usd", "input_tokens", "output_tokens")}})

    errs = [r for r in rows if r.get("status") != "ok"]
    rows_sorted = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    return {
        "window": window, "totals": _group(rows),
        "agents": {k: _group(v) for k, v in sorted(by_agent.items())},
        "models": {k: _group(v) for k, v in sorted(by_model.items())},
        "series": series,
        "recent_errors": [{k: r.get(k) for k in ("created_at", "agent", "model", "error", "latency_ms")} for r in sorted(errs, key=lambda r: r["created_at"], reverse=True)[:8]],
        "recent": [{k: r.get(k) for k in ("id", "created_at", "agent", "model", "status", "latency_ms", "input_tokens", "output_tokens", "cost_usd")} for r in rows_sorted[:25]],
    }
