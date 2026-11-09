"""
LLM performance and evaluation service. Agents report every model call to /api/ingest; this service stores them,
aggregates latency / errors / tokens / cost per agent and model, pulls traces from LangSmith, runs LLM-as-judge
evaluation suites, and checks the health of every other service.
"""

import asyncio
import logging
import hmac
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import httpx
from fastapi import Depends, Header, HTTPException, Request
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agentkit import office as office_mod
from agentkit import telemetry
from agentkit.app import create_service_app, mount_frontend
from agentkit.agentchat import register_agent_chat
from agentkit.auth import AuthUser, require_admin
from agentkit.cache import get_cache
from agentkit.llm import model_for
from agentkit.settings import get_settings
from agentkit.store import now_iso

from agentkit import apm as apm_mod

from . import collectors, dashboards as dash, designer, evals, watch as watch_mod
from .engine import AGGS as AGGS_Q
from .engine import CATALOG, Engine, MetricQuery
from .engine import WINDOWS as WINDOWS_Q
from .metrics import WINDOWS, summarize

AGENT = "observability"
TABLES = ["llm_calls", "eval_runs", "service_metrics", "dashboards"]
engine = Engine()
watcher = watch_mod.Watch(engine)
office = office_mod.Team("observability")


class CallIn(BaseModel):
    agent: str = Field(..., max_length=40)
    model: str = Field(..., max_length=120)
    status: str = "ok"
    error: Optional[str] = Field(None, max_length=400)
    latency_ms: int = Field(0, ge=0, le=3_600_000)
    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cost_usd: float = Field(0, ge=0)
    trace_id: Optional[str] = Field(None, max_length=80)
    meta: Optional[Dict[str, Any]] = None


async def _startup(app) -> None:
    loop = asyncio.get_running_loop()
    store = app.state.store

    def sink(rec: Dict[str, Any]) -> None:  # our own eval calls: record without an HTTP loopback
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(_save(store, rec)))

    telemetry.LOCAL_SINK = sink
    apm_mod.LOCAL_SINK = engine.ingest_sample  # this service's own CPU/memory/APM samples
    engine.llm_rows = lambda: store.select("llm_calls", order="created_at", limit=8000)
    n = await collectors.load_history(engine, store)
    app.state.bg = [asyncio.create_task(collectors.host_loop(engine)), asyncio.create_task(collectors.probe_loop(engine)),
                    asyncio.create_task(collectors.flush_loop(engine, store)), asyncio.create_task(watch_mod.run_watchers(watcher))]
    if n:
        logging.getLogger("obs").info("restored %d metric samples", n)


async def _save(store, rec: Dict[str, Any]) -> None:
    try:
        await store.insert("llm_calls", {"created_at": now_iso(), **rec})
    except Exception:
        pass


app = create_service_app(title="LLM Performance & Evaluation", agent=AGENT, tables=TABLES, features=["metrics", "evals", "langsmith", "services"], startup=[_startup])


@app.post("/api/ingest")
async def ingest(body: Union[CallIn, List[CallIn]], x_ingest_token: Optional[str] = Header(default=None)):
    if not hmac.compare_digest(x_ingest_token or "", get_settings().ingest_token):
        raise HTTPException(401, "Invalid ingest token")
    items = body if isinstance(body, list) else [body]
    if len(items) > 200:
        raise HTTPException(413, "Batch too large")
    now = now_iso()
    rows = [{"created_at": now, **c.model_dump(exclude_none=True)} for c in items]
    try:
        await app.state.store.insert_many("llm_calls", rows)
    except Exception:
        raise HTTPException(503, "Could not store telemetry")
    cache = get_cache()
    cache.set("overview:dirty", "1", ttl=5)
    return {"accepted": len(items)}


_ov_cache: Dict[str, Any] = {}


async def _rows(user: AuthUser, limit: int = 8000, include_loadtest: bool = False) -> List[Dict[str, Any]]:
    rows = await app.state.store.select("llm_calls", order="created_at", limit=limit, token=user.token)
    if include_loadtest:
        return rows
    return [r for r in rows if not (isinstance(r.get("meta"), dict) and r["meta"].get("loadtest"))]  # synthetic traffic from load tests


@app.get("/api/overview")
async def overview(window: str = "1h", user: AuthUser = Depends(require_admin)):
    if window not in WINDOWS:
        raise HTTPException(422, "window must be 1h, 24h or 7d")
    hit = _ov_cache.get(window)
    if hit and time.time() - hit[0] < 2:  # many dashboards polling: aggregate at most every 2 s
        return hit[1]
    data = summarize(await _rows(user), window)
    data["store"] = app.state.store.describe()["backend"]
    _ov_cache[window] = (time.time(), data)
    return data


_LS_CACHE: Dict[str, Any] = {}


def _langsmith_runs(limit: int) -> Dict[str, Any]:
    s = get_settings()
    if not s.langsmith_api_key:
        return {"enabled": False, "runs": []}
    from langsmith import Client

    client = Client(api_key=s.langsmith_api_key)
    runs = []
    for r in client.list_runs(project_name=s.langsmith_project, is_root=True, limit=limit):
        lat = (r.end_time - r.start_time).total_seconds() * 1000 if r.end_time and r.start_time else None
        runs.append({"id": str(r.id), "name": r.name, "status": r.status, "error": (r.error or "")[:160] or None,
                     "start": r.start_time.isoformat() if r.start_time else None, "latency_ms": round(lat) if lat else None,
                     "tokens": r.total_tokens, "tags": list(r.tags or [])[:4]})
    return {"enabled": True, "project": s.langsmith_project, "runs": runs}


@app.get("/api/langsmith")
async def langsmith(limit: int = 20, user: AuthUser = Depends(require_admin)):
    hit = _LS_CACHE.get(limit)
    if hit and time.time() - hit[0] < 15:
        return hit[1]
    try:
        data = await asyncio.wait_for(asyncio.to_thread(_langsmith_runs, min(limit, 50)), timeout=20)
    except Exception as exc:
        return {"enabled": True, "error": f"{type(exc).__name__}: {str(exc)[:160]}", "runs": []}
    _LS_CACHE[limit] = (time.time(), data)
    return data


@app.get("/api/evals/suites")
async def suites(user: AuthUser = Depends(require_admin)):
    return [{"id": k, "cases": [{"id": c.id, "prompt": c.prompt[:120]} for c in v]} for k, v in evals.SUITES.items()]


class EvalRequest(BaseModel):
    suite: str
    models: List[str] = ["primary", "secondary"]
    limit: Optional[int] = Field(None, ge=1, le=10)


@app.post("/api/evals/run", status_code=202)
async def run_eval(req: EvalRequest, user: AuthUser = Depends(require_admin)):
    if req.suite not in evals.SUITES:
        raise HTTPException(404, "Unknown suite")
    if not set(req.models) <= {"primary", "secondary"} or not req.models:
        raise HTTPException(422, "models must be primary and/or secondary")
    if any(r["status"] == "running" for r in evals.RUNS.values()):
        raise HTTPException(409, "An evaluation is already running")
    office("quality", "tool_call", f"Running suite {req.suite} on {len(req.models)} model(s)", state="working")
    run_id = await evals.run_suite(app.state.store, req.suite, req.models, req.limit)
    return {"run_id": run_id}


@app.get("/api/evals/runs/{run_id}")
async def eval_run(run_id: str, user: AuthUser = Depends(require_admin)):
    run = evals.RUNS.get(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    out = evals.summarize_run(run)
    if run["status"] == "done":
        office("quality", "done", f"Suite {run['suite']} finished", state="idle")
    return out


@app.get("/api/evals/history")
async def eval_history(user: AuthUser = Depends(require_admin)):
    rows = await app.state.store.select("eval_runs", order="created_at", limit=400, token=user.token)
    runs: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = r.get("run_id") or r["id"]
        g = runs.setdefault(k, {"run_id": k, "suite": r["suite"], "created_at": r["created_at"], "models": {}})
        m = g["models"].setdefault(r["model"], {"cases": 0, "passed": 0, "score": 0.0})
        m["cases"] += 1; m["passed"] += 1 if r.get("passed") else 0; m["score"] += float(r.get("score") or 0)
    out = []
    for g in runs.values():
        for m in g["models"].values():
            m["avg_score"] = round(m["score"] / m["cases"], 3); m["pass_rate"] = round(m["passed"] / m["cases"], 3); del m["score"]
        out.append(g)
    return sorted(out, key=lambda g: g["created_at"], reverse=True)[:15]


SERVICES = {k: v for k, v in collectors.SERVICES.items()}


@app.get("/api/services")
async def services(user: AuthUser = Depends(require_admin)):
    async def probe(c: httpx.AsyncClient, key: str, label: str, url: str):
        t = time.perf_counter()
        try:
            r = await c.get(url)
            body = r.json() if r.status_code == 200 else {}
            return {"id": key, "label": label, "up": r.status_code == 200, "ms": int((time.perf_counter() - t) * 1000), "store": body.get("store"), "cache": body.get("cache"), "llm_mode": body.get("llm_mode")}
        except Exception:
            return {"id": key, "label": label, "up": False, "ms": None}

    async with httpx.AsyncClient(timeout=2.5) as c:
        return await asyncio.gather(*[probe(c, k, *v) for k, v in SERVICES.items()])


@app.get("/api/loadtests")
async def loadtests(user: AuthUser = Depends(require_admin)):
    d = Path("data/loadtests")
    out = []
    for f in sorted(d.glob("*.json"), reverse=True)[:6] if d.is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- platform metrics (CPU, memory, APM)
class Sample(BaseModel):
    model_config = {"extra": "allow"}
    service: str = Field(..., max_length=40)
    ts: Optional[float] = None


@app.post("/api/metrics/ingest")
async def metrics_ingest(sample: Sample, x_ingest_token: Optional[str] = Header(default=None)):
    if not hmac.compare_digest(x_ingest_token or "", get_settings().ingest_token):
        raise HTTPException(401, "Invalid ingest token")
    engine.ingest_sample(sample.model_dump())
    return {"ok": True}


@app.get("/api/metrics/catalog")
async def metrics_catalog(user: AuthUser = Depends(require_admin)):
    return {"metrics": engine.describe(), "windows": list(WINDOWS_Q), "aggregations": AGGS_Q}


@app.post("/api/metrics/query")
async def metrics_query(q: MetricQuery, user: AuthUser = Depends(require_admin)):
    try:
        return await engine.query(q)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/platform")
async def platform(user: AuthUser = Depends(require_admin)):
    snap = engine.snapshot()
    avail = await engine.query(MetricQuery(metric="platform.availability", window="1h", by="service"))
    for sid, a in (avail["value"] or {}).items():
        if sid in snap["services"]:
            snap["services"][sid]["availability_1h"] = round(a, 2)
    for sid, (label, _) in collectors.SERVICES.items():
        snap["services"].setdefault(sid, {"up": False})["label"] = label
        snap["services"][sid]["label"] = label
    snap["slo"] = {"target": 99.0}
    return snap


# ---------------------------------------------------------------- incidents, delivery (CI/CD auto-heal), drift
@app.get("/api/incidents")
async def incidents(user: AuthUser = Depends(require_admin)):
    return watcher.summary()


@app.get("/api/delivery")
async def delivery(user: AuthUser = Depends(require_admin)):
    runs = sorted(engine.cicd_runs, key=lambda r: r["created_at"], reverse=True)[:30]
    finished = [r for r in runs if r["status"] in ("succeeded", "failed")]
    return {"runs": runs, "heal_log": engine.heal_log[:40], "error": engine.delivery_error,
            "policy": {"max_auto_heals": watch_mod.MAX_AUTO_HEALS, "auto": "transient failures (timeouts, rate limits, flaky network)",
                       "never_auto": "code, configuration and security failures: a person decides"},
            "stats": {"finished": len(finished), "success_rate": (sum(1 for r in finished if r["status"] == "succeeded") / len(finished)) if finished else None,
                      "auto_heals": sum(1 for h in engine.heal_log if h["action"] == "auto_rerun"), "healed": sum(1 for h in engine.heal_log if h["action"] == "healed"),
                      "needs_human": sum(1 for h in engine.heal_log if h["action"] == "needs_human")}}


@app.get("/api/drift")
async def drift(user: AuthUser = Depends(require_admin)):
    return engine.drift_state


@app.post("/api/drift/check")
async def drift_check_now(user: AuthUser = Depends(require_admin)):
    async with httpx.AsyncClient(timeout=15) as c:
        await watcher.drift_tick(c, force=True)
    return engine.drift_state


@app.post("/api/drift/{sid}/remediate")
async def drift_remediate(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    """Forwards the admin's explicit approval to the Infrastructure agent, which runs terraform apply."""
    async with httpx.AsyncClient(timeout=3700) as c:
        r = await c.post(f"{watch_mod.IAC}/iac/sessions/{sid}/drift/remediate", headers={"Authorization": request.headers.get("authorization", "")})
    if r.status_code != 200:
        raise HTTPException(r.status_code, (r.json() or {}).get("detail", "Remediation failed"))
    async with httpx.AsyncClient(timeout=15) as c:
        await watcher.drift_tick(c, force=True)
    return engine.drift_state


# ---------------------------------------------------------------- custom dashboards
class DesignRequest(BaseModel):
    messages: List[Dict[str, str]] = Field(..., min_length=1, max_length=40)
    current: Optional[Dict[str, Any]] = None
    model: str = "primary"


async def _custom(request: Request, user: AuthUser) -> List[Dict[str, Any]]:
    rows = await app.state.store.select("dashboards", order="created_at", limit=100, token=user.token)
    out = []
    for r in rows:
        spec = r.get("spec")
        if isinstance(spec, str):
            import json as _j
            spec = _j.loads(spec)
        out.append({"id": r["id"], "builtin": False, **(spec or {"title": r.get("title"), "widgets": []})})
    return out


@app.get("/api/dashboards")
async def list_dashboards(request: Request, user: AuthUser = Depends(require_admin)):
    custom = await _custom(request, user)
    return [{"id": d["id"], "title": d["title"], "description": d.get("description", ""), "builtin": d.get("builtin", False), "widgets": len(d["widgets"])} for d in dash.BUILTIN + custom]


@app.get("/api/dashboards/{did}")
async def get_dashboard(did: str, request: Request, user: AuthUser = Depends(require_admin)):
    for d in dash.BUILTIN + await _custom(request, user):
        if d["id"] == did:
            return d
    raise HTTPException(404, "Dashboard not found")


@app.post("/api/dashboards", status_code=201)
async def save_dashboard(d: dash.Dashboard, request: Request, user: AuthUser = Depends(require_admin)):
    errs = dash.validate_dashboard(d, engine)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    row = dash.to_row(d)
    await app.state.store.insert("dashboards", row, token=user.token)
    office("dashboard", "message", f"New dashboard saved: {d.title} ({len(d.widgets)} widgets)", state="idle")
    return {"id": row["id"], "builtin": False, **d.model_dump()}


@app.put("/api/dashboards/{did}")
async def update_dashboard(did: str, d: dash.Dashboard, request: Request, user: AuthUser = Depends(require_admin)):
    if did.startswith("builtin-"):
        raise HTTPException(409, "Built-in dashboards cannot be edited. Save a copy instead.")
    errs = dash.validate_dashboard(d, engine)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    if not await app.state.store.update("dashboards", {"id": did}, {"title": d.title, "spec": d.model_dump()}, token=user.token):
        raise HTTPException(404, "Dashboard not found")
    return {"id": did, "builtin": False, **d.model_dump()}


@app.delete("/api/dashboards/{did}")
async def delete_dashboard(did: str, request: Request, user: AuthUser = Depends(require_admin)):
    if did.startswith("builtin-"):
        raise HTTPException(409, "Built-in dashboards cannot be deleted.")
    await app.state.store.delete("dashboards", {"id": did}, token=user.token)
    return {"deleted": did}


@app.post("/api/dashboards/design")
async def design_dashboard(req: DesignRequest, user: AuthUser = Depends(require_admin)):
    if req.model not in ("primary", "secondary"):
        raise HTTPException(422, "Unknown model")
    office("dashboard", "tool_call", "Designing a dashboard from the conversation...", state="working")
    try:
        r = await designer.design(engine, req.messages, req.current, req.model)
    except Exception as exc:
        office("dashboard", "error", str(exc)[:200])
        raise HTTPException(502, str(exc)[:300])
    office("dashboard", "message", ("Asking: " + "; ".join(q["text"] for q in r["questions"]) if r["mode"] == "ask" else f"Designed '{r['dashboard']['title']}'")[:300], state="waiting" if r["mode"] == "ask" else "idle")
    return r


@app.post("/api/dashboards/render")
async def render_dashboard(d: dash.Dashboard, user: AuthUser = Depends(require_admin)):
    """Evaluates every widget of a (possibly unsaved) dashboard in one call."""
    errs = dash.validate_dashboard(d, engine)
    if errs:
        raise HTTPException(422, "; ".join(errs))
    out = []
    for w in d.widgets:
        out.append([await engine.query(q) for q in w.queries])
    return {"widgets": out}




# ---------------------------------------------------------------- conversation (the Agent Office talks to the observability team here)
class QueryArgs(BaseModel):
    metric: str = Field(..., description="A catalog key such as service.cpu_percent, service.latency_p95_ms, llm.cost_usd, cicd.success_rate")
    agg: Optional[str] = Field(None, description="avg, max, min, sum, last, p50, p95, p99 or rate")
    window: str = Field("1h", description="15m, 1h, 6h, 24h or 7d")
    by: Optional[str] = Field(None, description="split by service, agent, model or status where the metric allows")
    service: Optional[str] = Field(None, description="keep only this service: support, iac, cicd, office or observability")


class DesignArgs(BaseModel):
    request: str = Field(..., description="What the dashboard should show, in the admin's words, plus any answers they gave")


class NoArgs(BaseModel):
    pass


def _fmt(v: Any, unit: str = "") -> str:
    if v is None:
        return "no data"
    return f"{v:.3g} {unit}".strip() if isinstance(v, (int, float)) else str(v)


def _obs_tools(user, request, history):
    async def get_platform_status() -> str:
        snap = engine.snapshot()
        lines = [f"host: CPU {_fmt(snap['host'].get('cpu_percent'), '%')}, memory {_fmt(snap['host'].get('memory_percent'), '%')}, disk {_fmt(snap['host'].get('disk_percent'), '%')}"]
        for sid, s in snap["services"].items():
            state = "UP" if s.get("up") else ("unknown" if s.get("up") is None else "DOWN")
            lines.append(f"{sid}: {state}, CPU {_fmt(s.get('cpu_percent'), '%')}, memory {_fmt(s.get('memory_mb'), 'MB')}, {_fmt(s.get('rps'), 'req/s')}, p95 {_fmt(s.get('latency_p95_ms'), 'ms')}, errors {_fmt(s.get('error_rate'))}")
        inc = watcher.summary()
        lines.append(f"open incidents: {len(inc['open'])}, needing the admin: {len(inc['needs_you'])}")
        return "\n".join(lines)

    async def query_metric(metric: str, agg: Optional[str] = None, window: str = "1h", by: Optional[str] = None, service: Optional[str] = None) -> str:
        q = MetricQuery(metric=metric, agg=agg, window=window, by=by, where={"service": service} if service else {})
        try:
            r = await engine.query(q)
        except ValueError as exc:
            return f"Invalid query: {exc}"
        v = r["value"]
        body = ", ".join(f"{k}={_fmt(x, r['unit'])}" for k, x in v.items()) if isinstance(v, dict) else _fmt(v, r["unit"])
        return f"{r['label']} ({r['agg']}, last {r['window']}): {body}"

    async def list_incidents() -> str:
        s = watcher.summary()
        if not s["open"]:
            return "No open incidents."
        return "\n".join(f"[{i['severity']}] {i['title']}" + (f" | NEEDS YOU: {i['how_to_fix']}" if i["needs_user"] else "") for i in s["open"])

    async def get_delivery_status() -> str:
        d = await delivery(user)
        s = d["stats"]
        lines = [f"finished runs {s['finished']}, success rate {_fmt(s['success_rate'])}, auto-heal retries {s['auto_heals']}, healed {s['healed']}, needing a person {s['needs_human']}"]
        lines += [f"{h['action']}: {h['title']} ({h['reason']})" for h in d["heal_log"][:5]]
        return "\n".join(lines)

    async def get_drift_status() -> str:
        st = engine.drift_state.get("stacks", [])
        if not st:
            return "No applied stacks are being monitored yet." + (f" ({engine.drift_state['error']})" if engine.drift_state.get("error") else "")
        return "\n".join(f"{s['title']}: {s['status']}" + (f" ({len(s['findings'])} differences)" if s["findings"] else "") + (f" | {s['error']} FIX: {s['how_to_fix']}" if s.get("error") else "") for s in st)

    async def check_drift_now() -> str:
        async with httpx.AsyncClient(timeout=15) as c:
            await watcher.drift_tick(c, force=True)
        return await get_drift_status()

    async def design_dashboard(request: str) -> str:
        msgs = [m for m in history if m["role"] in ("user", "assistant")][-12:] or [{"role": "user", "content": request}]
        msgs[-1] = {"role": "user", "content": msgs[-1]["content"] + ("" if request in msgs[-1]["content"] else f"\n(Design request: {request})")}
        try:
            r = await designer.design(engine, msgs, None, "primary")
        except Exception as exc:
            return f"Could not design it: {exc}"
        if r["mode"] == "ask":
            qs = "\n".join(f"- {q['text']}" + (f" [{' | '.join(q['options'])}]" if q["options"] else "") for q in r["questions"])
            return "The designer needs these answers first. Relay ALL of them to the admin exactly as written, then wait:\n" + qs
        d = dash.Dashboard.model_validate(r["dashboard"])
        row = dash.to_row(d)
        await app.state.store.insert("dashboards", row, token=user.token)
        return f"Saved dashboard '{d.title}' (id {row['id']}) with {len(d.widgets)} widgets: " + ", ".join(w.title for w in d.widgets[:8]) + ". Open it in the Observability app under Dashboards (http://localhost:8400)."

    mk = StructuredTool.from_function
    return {x.name: x for x in [
        mk(coroutine=get_platform_status, name="get_platform_status", args_schema=NoArgs, description="Right now: is each service up, and its CPU, memory, throughput, latency, errors; machine health; incident counts."),
        mk(coroutine=query_metric, name="query_metric", args_schema=QueryArgs, description="Any metric from the catalog over a time window. Use it for every number you quote."),
        mk(coroutine=list_incidents, name="list_incidents", args_schema=NoArgs, description="Open incidents and which of them need the admin."),
        mk(coroutine=get_delivery_status, name="get_delivery_status", args_schema=NoArgs, description="CI/CD health and what the auto-heal loop did."),
        mk(coroutine=get_drift_status, name="get_drift_status", args_schema=NoArgs, description="Whether infrastructure still matches its code."),
        mk(coroutine=check_drift_now, name="check_drift_now", args_schema=NoArgs, description="Run a drift check on every applied stack right now."),
        mk(coroutine=design_dashboard, name="design_dashboard", args_schema=DesignArgs, description="Design and save a custom dashboard. It may return questions to relay first."),
    ]}


def _obs_prompt(user) -> str:
    cats = ", ".join(sorted({m.group for m in CATALOG.values()}))
    return f"""You are Cleo, speaking for the observability team (the heart of the platform) to the admin. The team watches the platform's services (support, iac, cicd, office, observability), the machine, model usage and cost, CI/CD pipelines (and heals transient failures on its own), and infrastructure drift. Metric groups: {cats}.

Rules:
1. Facts come from tools; never invent a number. Quote units. If a tool has no data say so.
2. ASK FIRST, ONCE when a request is ambiguous (especially custom dashboards): put ALL the questions in one message, each with clickable choices like "Which time range? [1h * | 6h | 24h]". design_dashboard may hand you questions: relay them all, exactly, and wait for the answers. Never trickle questions across rounds.
3. Anything only the admin can fix (a service that is down, missing credentials or Terraform, a failing pipeline that needs a code fix, drift awaiting approval) must start with "Needs you:" and say exactly what to do. Never claim you fixed something you did not.
4. You can retry transient pipeline failures automatically (at most twice). You never change code or infrastructure on your own: drift is only put back after the admin clicks approve.
5. Be brief. Use the <ui> element for stats or charts only when numbers deserve a picture."""


register_agent_chat(app, agent="observability", team="observability", voice="collector", system_prompt=_obs_prompt, tools=_obs_tools,
                    tool_voice=lambda n: {"get_platform_status": "otel", "query_metric": "store", "list_incidents": "scribe", "get_delivery_status": "failures",
                                          "get_drift_status": "anomaly", "check_drift_now": "anomaly", "design_dashboard": "dashboard"}.get(n, "collector"))


mount_frontend(app, str(Path(__file__).resolve().parent.parent / "frontend"))
