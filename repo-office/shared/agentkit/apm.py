"""
Application performance monitoring built into every service. Measures the "golden signals" plus saturation and pushes a
sample to the observability service every few seconds:

    traffic      requests/s                      latency   p50 / p95 / p99 of request handling
    errors       5xx and 4xx rates               saturation  process CPU, resident memory, threads, open handles,
                                                              in-flight requests, event-loop lag
    identity     service name, pid, uptime

Reporting is fire-and-forget: if the observability service is down the sample is dropped and the service carries on.
"""

import asyncio
import json
import os
import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional

import psutil

from .settings import get_settings

PUSH_SECONDS = 10


def _pct(vals: List[float], p: float) -> float:
    if not vals:
        return 0.0
    v = sorted(vals)
    k = (len(v) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


class Apm:
    def __init__(self, service: str) -> None:
        self.service = service
        self.proc = psutil.Process(os.getpid())
        self.proc.cpu_percent(None)  # prime: the first call always returns 0
        self.cores = psutil.cpu_count() or 1
        self.started = time.time()
        self.lock = threading.Lock()
        self.inflight = 0
        self.lag_samples: List[float] = []
        self._reset()
        self.routes: Dict[str, List[float]] = defaultdict(lambda: [0, 0, 0.0])  # path -> count, errors, total ms

    def _reset(self) -> None:
        self.n = self.e5 = self.e4 = 0
        self.lat: List[float] = []

    def record(self, route: str, status: int, ms: float) -> None:
        with self.lock:
            self.n += 1
            self.e5 += status >= 500
            self.e4 += 400 <= status < 500
            if len(self.lat) < 5000:
                self.lat.append(ms)
            r = self.routes[route]
            r[0] += 1
            r[1] += status >= 500
            r[2] += ms

    def snapshot(self, interval: float) -> Dict[str, Any]:
        with self.lock:
            n, e5, e4, lat = self.n, self.e5, self.e4, self.lat
            self._reset()
            lag = self.lag_samples
            self.lag_samples = []
            top = sorted(self.routes.items(), key=lambda kv: -kv[1][0])[:8]
        try:
            mem = self.proc.memory_info()
            cpu = self.proc.cpu_percent(None)  # % of ONE core since the last call
            handles = self.proc.num_handles() if hasattr(self.proc, "num_handles") else self.proc.num_fds()
            threads = self.proc.num_threads()
        except psutil.Error:
            mem, cpu, handles, threads = None, 0.0, 0, 0
        return {
            "service": self.service, "pid": os.getpid(), "ts": time.time(), "uptime_s": round(time.time() - self.started),
            "cpu_percent": round(cpu / self.cores, 2),            # share of the whole machine this process uses
            "cpu_core_percent": round(cpu, 2),                     # share of one core (can exceed 100)
            "memory_mb": round(mem.rss / 2**20, 1) if mem else 0, "threads": threads, "handles": handles, "inflight": self.inflight,
            "rps": round(n / interval, 3), "requests": n, "errors_5xx": e5, "errors_4xx": e4,
            "error_rate": round(e5 / n, 4) if n else 0.0,
            "latency_p50_ms": round(_pct(lat, 0.5), 1), "latency_p95_ms": round(_pct(lat, 0.95), 1), "latency_p99_ms": round(_pct(lat, 0.99), 1),
            "loop_lag_ms": round(max(lag), 1) if lag else 0.0,
            "top_routes": [{"route": k, "count": int(v[0]), "errors": int(v[1]), "avg_ms": round(v[2] / v[0], 1)} for k, v in top],
        }


_apm: Dict[str, Apm] = {}
LOCAL_SINK: Optional[Callable[[Dict[str, Any]], None]] = None  # the observability service records its own samples directly


def get_apm(service: str) -> Apm:
    return _apm[service]


async def _lag_probe(a: Apm) -> None:
    while True:
        t = time.perf_counter()
        await asyncio.sleep(0.25)
        a.lag_samples.append(max(0.0, (time.perf_counter() - t - 0.25) * 1000))
        if len(a.lag_samples) > 400:
            del a.lag_samples[:200]


def _post(sample: Dict[str, Any]) -> None:
    import urllib.request

    s = get_settings()
    req = urllib.request.Request(f"{s.obs_url.rstrip('/')}/api/metrics/ingest", data=json.dumps(sample).encode(),
                                 headers={"Content-Type": "application/json", "X-Ingest-Token": s.ingest_token})
    urllib.request.urlopen(req, timeout=3).read()


async def _push_loop(a: Apm) -> None:
    while True:
        await asyncio.sleep(PUSH_SECONDS)
        sample = a.snapshot(PUSH_SECONDS)
        try:
            if LOCAL_SINK is not None:
                LOCAL_SINK(sample)
            elif get_settings().obs_url:
                await asyncio.to_thread(_post, sample)
        except Exception:
            pass


def install_apm(app, service: str) -> Apm:
    """Adds request measurement and the background sampler to a FastAPI app (works with or without a lifespan)."""
    a = _apm[service] = Apm(service)

    @app.middleware("http")
    async def apm_middleware(request, call_next):
        t = time.perf_counter()
        a.inflight += 1
        status = 500
        try:
            resp = await call_next(request)
            status = resp.status_code
            return resp
        finally:
            a.inflight -= 1
            route = request.scope.get("route")
            path = getattr(route, "path", None) or ("static" if status < 400 else "unmatched")
            if path != "/health":  # health probes would drown real traffic
                a.record(f"{request.method} {path}", status, (time.perf_counter() - t) * 1000)

    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        tasks = [asyncio.create_task(_lag_probe(a)), asyncio.create_task(_push_loop(a))]
        try:
            async with original(application) as state:
                yield state
        finally:
            for t in tasks:
                t.cancel()

    app.router.lifespan_context = lifespan
    return a
