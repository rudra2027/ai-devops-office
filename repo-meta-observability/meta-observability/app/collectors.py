"""Background collectors: host metrics, service health probes, and persistence of samples."""

import asyncio
import logging
import time
from typing import Dict, Tuple

import httpx
import psutil

from agentkit.store import now_iso

from .engine import Engine

log = logging.getLogger("obs.collectors")

# id -> (label, health url). ids match the `service` name each service reports about itself.
SERVICES: Dict[str, Tuple[str, str]] = {
    "support": ("Support chat", "http://127.0.0.1:8000/health"),
    "iac": ("Infrastructure agent", "http://127.0.0.1:8100/health"),
    "cicd": ("CI/CD agent", "http://127.0.0.1:8300/health"),
    "office": ("Agent Office", "http://127.0.0.1:8200/health"),
    "observability": ("Observability", "http://127.0.0.1:8400/health"),
}


async def host_loop(engine: Engine, every: float = 10) -> None:
    psutil.cpu_percent(None)
    disk = "C:\\" if psutil.WINDOWS else "/"
    while True:
        await asyncio.sleep(every)
        try:
            ts = time.time()
            engine.tsdb.add("host.cpu_percent", "host", ts, psutil.cpu_percent(None))
            engine.tsdb.add("host.memory_percent", "host", ts, psutil.virtual_memory().percent)
            engine.tsdb.add("host.disk_percent", "host", ts, psutil.disk_usage(disk).percent)
        except Exception:
            log.exception("host sample failed")


async def probe_loop(engine: Engine, every: float = 10) -> None:
    async with httpx.AsyncClient(timeout=2.5) as c:
        async def one(sid: str, url: str) -> None:
            t = time.perf_counter()
            try:
                ok = (await c.get(url)).status_code == 200
            except Exception:
                ok = False
            ts = time.time()
            engine.tsdb.add("service.up", sid, ts, 1.0 if ok else 0.0)
            if ok:
                engine.tsdb.add("service.health_ms", sid, ts, (time.perf_counter() - t) * 1000)

        while True:
            await asyncio.gather(*[one(sid, url) for sid, (_, url) in SERVICES.items()])
            await asyncio.sleep(every)


async def flush_loop(engine: Engine, store, every: float = 30) -> None:
    """Persists pushed samples so history survives a restart."""
    while True:
        await asyncio.sleep(every)
        batch, engine.pending = engine.pending, []
        if not batch:
            continue
        try:
            await store.insert_many("service_metrics", [{"service": s["service"], "data": s, "created_at": now_iso()} for s in batch])
        except Exception as exc:
            log.warning("could not persist %d samples: %s", len(batch), exc)


async def load_history(engine: Engine, store, token=None) -> int:
    try:
        rows = await store.select("service_metrics", order="created_at", limit=6000, token=token)
    except Exception:
        return 0
    n = 0
    for r in reversed(rows):  # oldest first
        d = r.get("data")
        if isinstance(d, str):
            import json

            d = json.loads(d)
        if isinstance(d, dict) and d.get("service"):
            engine.tsdb.add_sample(d)
            n += 1
    return n
