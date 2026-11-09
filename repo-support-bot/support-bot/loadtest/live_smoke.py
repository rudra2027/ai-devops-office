"""
Small LIVE load test with real models (costs a few cents): N chats at a fixed concurrency, alternating both models.

    python loadtest/live_smoke.py --base http://127.0.0.1:8020 --chats 12 --concurrency 4
"""

import argparse
import asyncio
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import httpx

PROMPTS = ["Where is my order 4412?", "Is order 9001 delayed? I need to know.", "What can you help me with?", "Check order 5120 and tell me when it arrives.",
           "I received a damaged item from order 7788, please open a ticket.", "Say hello in one short sentence."]


async def one(c: httpx.AsyncClient, i: int, base: str):
    model = "primary" if i % 2 == 0 else "secondary"
    t0 = time.perf_counter()
    first, done, err, tools = None, None, None, 0
    try:
        async with c.stream("POST", f"{base}/api/chat", json={"message": PROMPTS[i % len(PROMPTS)], "model": model}, headers={"Authorization": f"Bearer dev:live{i}@example.com"}, timeout=120) as r:
            if r.status_code != 200:
                return {"model": model, "error": f"HTTP {r.status_code}"}
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:])
                if ev["type"] == "token" and first is None:
                    first = (time.perf_counter() - t0) * 1000
                elif ev["type"] == "tool_start":
                    tools += 1
                elif ev["type"] == "done":
                    done = ev
                elif ev["type"] == "error":
                    err = ev["message"]
    except Exception as exc:
        err = type(exc).__name__
    return {"model": model, "first_ms": first, "total_ms": (time.perf_counter() - t0) * 1000, "tokens_out": (done or {}).get("usage", {}).get("output_tokens"), "tools": tools, "ok": bool(done) and not err, "error": err, "has_ui": bool(done and done.get("ui"))}


async def main(a):
    sem = asyncio.Semaphore(a.concurrency)
    async with httpx.AsyncClient() as c:
        async def run(i):
            async with sem:
                return await one(c, i, a.base)
        t0 = time.perf_counter()
        res = await asyncio.gather(*[run(i) for i in range(a.chats)])
        wall = time.perf_counter() - t0
    ok = [r for r in res if r.get("ok")]
    def q(vals, p):
        vals = sorted(vals)
        return round(vals[min(len(vals) - 1, int(len(vals) * p))]) if vals else None
    out = {"chats": a.chats, "concurrency": a.concurrency, "succeeded": len(ok), "failed": a.chats - len(ok), "wall_s": round(wall, 1),
           "first_token_ms p50/p95": f"{q([r['first_ms'] for r in ok if r['first_ms']], .5)} / {q([r['first_ms'] for r in ok if r['first_ms']], .95)}",
           "total_ms p50/p95": f"{q([r['total_ms'] for r in ok], .5)} / {q([r['total_ms'] for r in ok], .95)}",
           "answers with tool calls": sum(1 for r in ok if r["tools"]), "answers with generative UI": sum(1 for r in ok if r["has_ui"])}
    for m in ("primary", "secondary"):
        t = [r["total_ms"] for r in ok if r["model"] == m]
        if t:
            out[f"{m} avg total (ms)"] = round(statistics.mean(t))
    errs = [r["error"] for r in res if r.get("error")]
    if errs:
        out["errors"] = errs[:5]
    print(json.dumps(out, indent=1))
    d = Path(a.out)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{datetime.now():%Y%m%d-%H%M%S}-support-live.json").write_text(json.dumps({"name": f"support · live models · {a.chats} chats @ {a.concurrency}", "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "summary": out}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8020")
    ap.add_argument("--chats", type=int, default=12)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / ".." / "repo-meta-observability" / "meta-observability" / "data" / "loadtests"))
    main_args = ap.parse_args()
    asyncio.run(main(main_args))
