"""CI/CD agent API: submit a change, get an LLM review and plain-language summary, approve it, watch the pipeline run."""

import asyncio
import hmac
import os
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, Header, HTTPException, Request
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from agentkit.app import create_service_app, mount_frontend
from agentkit.agentchat import register_agent_chat
from agentkit.auth import AuthUser, require_admin
from agentkit.cache import rate_limited
from agentkit.settings import get_settings

from . import runs, stages
from .samples import BY_ID, SAMPLES

app = create_service_app(title="CI/CD Agent", agent="cicd", tables=[runs.TABLE], features=["review", "approval", "pipeline", "self-heal"])

_default_roots = Path(__file__).resolve().parents[3]  # the multiagent folder
ROOTS: List[Path] = [Path(p).resolve() for p in os.environ.get("CICD_ALLOWED_ROOTS", str(_default_roots)).split(os.pathsep) if p]
MAX_DIFF = 200_000


class NewRun(BaseModel):
    title: str = Field("", max_length=80)
    diff: Optional[str] = Field(None, max_length=MAX_DIFF)
    sample_id: Optional[str] = None
    repo_path: Optional[str] = None
    base: str = "HEAD~1"
    head: str = "HEAD"
    test_command: str = Field("", max_length=200)
    model: str = "primary"


class Approval(BaseModel):
    override_warnings: bool = False


def _persist(request: Request):
    store = request.app.state.store
    token = request.headers.get("authorization", "")[7:] or None

    async def go(run) -> None:
        row = {"user_id": run["user_id"], "repo": run.get("repo"), "ref": f"{run.get('base')}..{run.get('head')}" if run.get("repo") else None, "status": run["status"], "data": runs.public(run) | {"diff": run["diff"]}}
        try:
            if not await store.update(runs.TABLE, {"id": run["id"]}, row, token=token):
                await store.insert(runs.TABLE, {"id": run["id"], **row}, token=token)
        except Exception:
            pass  # e.g. a webhook run with no user token under row level security: it stays available in memory

    return go


async def _get(request: Request, rid: str, user: AuthUser) -> dict:
    run = runs._runs.get(rid)
    if run is None:
        rows = await request.app.state.store.select(runs.TABLE, {"id": rid}, order=None, limit=1, token=user.token)
        if not rows:
            raise HTTPException(404, "Run not found")
        data = rows[0].get("data") or {}
        if isinstance(data, str):
            import json

            data = json.loads(data)
        run = {**data, "user_id": rows[0].get("user_id"), "diff": data.get("diff", "")}
        runs._runs[rid] = run
    return run


@app.get("/api/samples")
async def samples(user: AuthUser = Depends(require_admin)):
    return [{k: s[k] for k in ("id", "label", "blurb", "title")} for s in SAMPLES]


@app.get("/api/runs")
async def list_runs(request: Request, user: AuthUser = Depends(require_admin)):
    rows = await request.app.state.store.select(runs.TABLE, {}, order="created_at", limit=60, token=user.token)
    out = []
    stored = {r["id"] for r in rows}
    rows = rows + [{"id": rid, "status": run["status"]} for rid, run in runs._runs.items() if rid not in stored]  # runs not (yet) in the database
    for r in rows:
        live = runs._runs.get(r["id"])
        d = (live and runs.public(live)) or (r.get("data") if isinstance(r.get("data"), dict) else {})
        out.append({"id": r["id"], "title": d.get("title", "Change"), "status": (live or r).get("status"), "created_at": d.get("created_at"), "risk": ((d.get("review") or {}).get("risk"))})
    return out


async def _make_run(body: "NewRun", request: Request, user: AuthUser) -> dict:
    if rate_limited(f"cicd:{user.id}", 10):
        raise HTTPException(429, "Too many runs started in a minute. Try again shortly.")
    if body.model not in ("primary", "secondary"):
        raise HTTPException(422, "Unknown model")
    title, repo, source = body.title, None, "diff"
    if body.sample_id:
        s = BY_ID.get(body.sample_id)
        if not s:
            raise HTTPException(404, "Unknown sample")
        diff, title = s["diff"], title or s["title"]
    elif body.repo_path:
        try:
            p = stages.safe_repo(body.repo_path, ROOTS)
            diff = await asyncio.to_thread(stages.git_diff, p, body.base, body.head)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc))
        repo, source, title = str(p), "repo", title or f"{p.name} {body.base}..{body.head}"
    elif body.diff:
        diff = body.diff
    else:
        raise HTTPException(422, "Provide a diff, a sample_id or a repo_path")
    if not diff.strip():
        raise HTTPException(400, "The change is empty: nothing to review")
    run = runs.new_run(user.id, title, diff, source, body.model, repo, body.base, body.head, body.test_command)
    persist = _persist(request)
    await persist(run)
    asyncio.create_task(runs.start_review(run, persist))
    return runs.public(run)


@app.post("/api/runs", status_code=202)
async def create_run(body: NewRun, request: Request, user: AuthUser = Depends(require_admin)):
    return await _make_run(body, request, user)


class WebhookChange(BaseModel):
    repo_path: str
    base: str = "HEAD~1"
    head: str = "HEAD"
    title: str = Field("", max_length=80)


@app.post("/api/webhook/change", status_code=202)
async def webhook(body: WebhookChange, request: Request, x_webhook_token: Optional[str] = Header(default=None)):
    """Lets a git hook or CI system start a review without anyone opening the UI. Disabled unless CICD_WEBHOOK_TOKEN is set.
    The run waits for the admin's approval like any other."""
    token = get_settings().cicd_webhook_token
    if not token:
        raise HTTPException(404, "Webhook is not enabled")
    if not hmac.compare_digest(x_webhook_token or "", token):
        raise HTTPException(401, "Invalid webhook token")
    try:
        p = stages.safe_repo(body.repo_path, ROOTS)
        diff = await asyncio.to_thread(stages.git_diff, p, body.base, body.head)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc))
    if not diff.strip():
        raise HTTPException(400, "The change is empty: nothing to review")
    run = runs.new_run(None, body.title or f"{p.name} {body.base}..{body.head}", diff, "repo", "primary", str(p), body.base, body.head)
    persist = _persist(request)
    await persist(run)
    asyncio.create_task(runs.start_review(run, persist))
    return {"id": run["id"], "status": run["status"]}


@app.get("/api/runs/{rid}")
async def get_run(rid: str, request: Request, user: AuthUser = Depends(require_admin)):
    return runs.public(await _get(request, rid, user))


@app.post("/api/runs/{rid}/approve")
async def approve(rid: str, request: Request, body: Optional[Approval] = None, user: AuthUser = Depends(require_admin)):
    run = await _get(request, rid, user)
    if run["status"] != "awaiting_approval":
        raise HTTPException(409, f"Run is {run['status']}, not awaiting approval")
    if runs.hard_blockers(run):
        raise HTTPException(409, "A secret was found in the change. Remove and rotate it, then submit the change again. This cannot be overridden.")
    review = run["review"] or {}
    if any(f["severity"] == "blocker" for f in review.get("findings", [])) and not (body and body.override_warnings):
        raise HTTPException(409, "The reviewer found blockers. Approve again with override to proceed anyway.")
    run["approved_by"] = user.email or user.id
    persist = _persist(request)
    runs._ev(run, "reviewer", "handoff", f"Summary approved by {run['approved_by']}.", state="idle", to_member="tester")
    asyncio.create_task(runs.execute(run, persist, ROOTS))
    run["status"] = "running"
    await persist(run)
    return runs.public(run)


@app.post("/api/runs/{rid}/reject")
async def reject(rid: str, request: Request, user: AuthUser = Depends(require_admin)):
    run = await _get(request, rid, user)
    if run["status"] != "awaiting_approval":
        raise HTTPException(409, f"Run is {run['status']}, not awaiting approval")
    run["status"], run["rejected_by"] = "rejected", user.email or user.id
    runs._ev(run, "reviewer", "message", f"Change rejected by {run['rejected_by']}.", state="idle")
    await _persist(request)(run)
    return runs.public(run)


@app.post("/api/runs/{rid}/rerun")
async def rerun(rid: str, request: Request, user: AuthUser = Depends(require_admin)):
    run = await _get(request, rid, user)
    if run["status"] not in ("failed", "succeeded"):
        raise HTTPException(409, "Only finished runs can be re-run")
    runs.restart(run, auto=False)
    asyncio.create_task(runs.execute(run, _persist(request), ROOTS))
    return runs.public(run)


# ---- internal API for the observability service (monitoring and auto-heal). Authenticated with the shared service token.
def _service(x_ingest_token: Optional[str]) -> None:
    if not hmac.compare_digest(x_ingest_token or "", get_settings().ingest_token):
        raise HTTPException(401, "Invalid service token")


@app.get("/api/internal/runs")
async def internal_runs(x_ingest_token: Optional[str] = Header(default=None)):
    _service(x_ingest_token)
    out = []
    for r in runs._runs.values():
        out.append({"id": r["id"], "title": r["title"], "status": r["status"], "created_at": r["created_at"], "updated_at": r["updated_at"], "model": r["model"],
                    "heal_attempts": r.get("heal_attempts", 0), "risk": (r.get("review") or {}).get("risk"), "heal": r.get("heal"), "attention": r.get("attention", []),
                    "stages": [{"id": s["id"], "status": s["status"], "duration_ms": s["duration_ms"], "log_tail": (s["log"] or "")[-600:]} for s in r["stages"]]})
    return sorted(out, key=lambda r: r["created_at"], reverse=True)[:100]


@app.post("/api/internal/runs/{rid}/auto-heal")
async def internal_auto_heal(rid: str, request: Request, x_ingest_token: Optional[str] = Header(default=None)):
    """Re-run a failed pipeline on the platform's own initiative. Only transient failures, only a few times."""
    _service(x_ingest_token)
    run = runs._runs.get(rid)
    if run is None:
        raise HTTPException(404, "Run not found")
    kind = (run.get("heal") or {}).get("kind")
    if run["status"] != "failed" or kind != "transient":
        raise HTTPException(409, "Only failed runs with a transient cause are retried automatically")
    if run.get("heal_attempts", 0) >= runs.MAX_AUTO_HEALS:
        raise HTTPException(409, "Automatic retries are used up; a person has to look at this one")
    runs.restart(run, auto=True, reason=(run.get("heal") or {}).get("diagnosis", "")[:160])
    asyncio.create_task(runs.execute(run, _persist(request), ROOTS))
    return {"id": rid, "attempt": run["heal_attempts"]}


@app.delete("/api/runs/{rid}")
async def delete_run(rid: str, request: Request, user: AuthUser = Depends(require_admin)):
    await _get(request, rid, user)
    runs._runs.pop(rid, None)
    await request.app.state.store.delete(runs.TABLE, {"id": rid}, token=user.token)
    return {"deleted": rid}




# ---------------------------------------------------------------- conversation (the Agent Office talks to Cody here)
class StartReviewArgs(BaseModel):
    repo_path: Optional[str] = Field(None, description="Local git repository to review, e.g. D:\\multiagent\\repo-office")
    base: str = Field("HEAD~1", description="git ref to compare from")
    head: str = Field("HEAD", description="git ref to compare to")
    diff: Optional[str] = Field(None, description="A pasted unified diff, instead of a repository")
    sample_id: Optional[str] = Field(None, description="clean-refactor, sql-injection or secret-leak: built-in practice changes")
    title: str = ""
    test_command: str = Field("", description="Only if the project's tests are not run by plain pytest/npm test")


class RunIdArgs(BaseModel):
    run_id: str


class NoArgs(BaseModel):
    pass


def _brief(r: dict) -> str:
    rv = r.get("review") or {}
    att = "; ".join(a["title"] for a in r.get("attention", []) if a.get("severity") != "info")
    return (f"{r['id']}: '{r['title']}' is {r['status']}" + (f", risk {rv.get('risk')}" if rv else "") + (f", {len(rv.get('findings', []))} finding(s)" if rv else "")
            + (f", auto-heal retries {r.get('heal_attempts')}" if r.get("heal_attempts") else "") + (f". NEEDS YOU: {att}" if att else ""))


def _cody_tools(user, request, history):
    async def list_runs() -> str:
        rows = sorted(runs._runs.values(), key=lambda r: r["created_at"], reverse=True)[:8]
        return "\n".join(_brief(r) for r in rows) or "No runs yet."

    async def get_run(run_id: str) -> str:
        r = runs._runs.get(run_id)
        if not r:
            return "No run with that id."
        rv = r.get("review") or {}
        lines = [_brief(r)] + [f"- [{f['severity']}] {f['file']}: {f['issue']}" for f in rv.get("findings", [])[:6]]
        lines += [f"stage {s['id']}: {s['status']}" for s in r["stages"]]
        if r.get("heal"):
            lines.append(f"diagnosis ({r['heal'].get('kind')}): {r['heal'].get('diagnosis')}")
        return "\n".join(lines)

    async def start_review(**kw) -> str:
        try:
            run = await _make_run(NewRun(**{k: v for k, v in kw.items() if v not in (None, "")}), request, user)
        except HTTPException as exc:
            return f"Could not start: {exc.detail}"
        return f"Started review {run['id']} ('{run['title']}'). When the summary is ready the admin approves it in the CI/CD app (http://localhost:8300). Nothing runs before that."

    async def rerun_run(run_id: str) -> str:
        r = runs._runs.get(run_id)
        if not r or r["status"] not in ("failed", "succeeded"):
            return "Only finished runs can be re-run."
        runs.restart(r, auto=False)
        asyncio.create_task(runs.execute(r, _persist(request), ROOTS))
        return f"Re-running {run_id}."

    mk = StructuredTool.from_function
    return {t.name: t for t in [
        mk(coroutine=list_runs, name="list_runs", args_schema=NoArgs, description="Recent pipeline runs and their status, including anything that needs the admin."),
        mk(coroutine=get_run, name="get_run", args_schema=RunIdArgs, description="Details of one run: summary, findings, stages, failure diagnosis."),
        mk(coroutine=start_review, name="start_review", args_schema=StartReviewArgs, description="Begin reviewing a change. Only call this once you have everything you need."),
        mk(coroutine=rerun_run, name="rerun_run", args_schema=RunIdArgs, description="Run a finished pipeline's stages again (only when the admin asked)."),
    ]}


def _cody_prompt(user) -> str:
    return """You are Cody, the CI/CD team's reviewer, talking to the platform admin. You take changes, get them reviewed and shipped.

Rules:
1. ASK FIRST, ONCE. Before starting anything make sure you know what to review (a local repository path with the two refs, a pasted diff, or one of the practice samples) and anything unusual (a custom test command). If something is missing, ask ALL of it in a single message, each question with clickable choices like: "Which change? [latest commit of repo-office * | a pasted diff | a practice sample]". Do not start until the answers are in. Do not ask what they already said.
2. Facts come from tools (list_runs, get_run). Never guess a status.
3. Once you start a review say what happens next: you write a plain-language summary, the admin approves the summary (never the raw diff), then tests, scan, build and rollout run. You cannot approve for them.
4. Anything only a person can fix (a leaked secret, a failing test, missing configuration) must be said plainly, starting with "Needs you:", with exactly what to do.
5. Be brief and concrete. Allowed repositories are under D:\\multiagent."""


register_agent_chat(app, agent="cicd", team="cicd", voice="reviewer", system_prompt=_cody_prompt, tools=_cody_tools,
                    tool_voice=lambda n: {"list_runs": "tester", "get_run": "tester", "start_review": "reviewer", "rerun_run": "release"}.get(n, "reviewer"))


mount_frontend(app, str(Path(__file__).resolve().parent.parent / "frontend"))
