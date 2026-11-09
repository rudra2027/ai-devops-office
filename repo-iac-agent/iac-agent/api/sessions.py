"""
Conversational provisioning API. Admin only: the admin owns every session.
Sessions live in memory while active and are persisted (Supabase or the SQLite fallback) after every change.
"""

import asyncio
import hmac
import io
import time
import zipfile
from typing import Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agentkit.auth import AuthUser, require_admin
from agentkit.cache import rate_limited
from agentkit.settings import get_settings
from agentkit.store import now_iso

from app.provisioner import documents, operator, pipeline, stacks
from app.provisioner.llm import build_llm, provisioner_settings

router = APIRouter(prefix="/iac", tags=["provisioner"])
TABLE = "iac_sessions"
_live: Dict[str, pipeline.Session] = {}

EXAMPLES = [
    {"cloud": "Hetzner", "prompt": "A small web app on Hetzner in Falkenstein with a Postgres database and a bucket for uploads."},
    {"cloud": "AWS", "prompt": "A private VPC on AWS in eu-west-1 with two web servers behind a load balancer and an S3 bucket."},
    {"cloud": "Azure", "prompt": "A public web app on Azure in West Europe with a SQL database and a storage account for files."},
    {"cloud": "Google Cloud", "prompt": "Process uploads on Google Cloud: a storage bucket, a Pub/Sub queue and a Cloud Run service."},
    {"cloud": "Oracle", "prompt": "A virtual machine and an object storage bucket on Oracle Cloud in Frankfurt."},
    {"cloud": "DigitalOcean", "prompt": "A Kubernetes cluster with 3 nodes and a managed Postgres database on DigitalOcean, NYC region."},
]


class UserMessage(BaseModel):
    content: str = Field(..., min_length=1, max_length=4000)
    model: str = "primary"


class NewSession(BaseModel):
    model: str = "primary"


async def _persist(request: Request, s: pipeline.Session) -> None:
    store = request.app.state.store
    row = {"user_id": s.user_id, "status": s.status.value, "data": s.public()}
    token = request.headers.get("authorization", "")[7:] or None
    if not await store.update(TABLE, {"id": s.id}, row, token=token):
        await store.insert(TABLE, {"id": s.id, **row}, token=token)


async def _load(request: Request, sid: str, user: AuthUser) -> pipeline.Session:
    s = _live.get(sid)
    if s is None:
        rows = await request.app.state.store.select(TABLE, {"id": sid}, order=None, limit=1, token=user.token)
        if not rows:
            raise HTTPException(404, "Session not found")
        data = rows[0].get("data")
        if isinstance(data, str):
            import json

            data = json.loads(data)
        s = pipeline.Session.from_public(data, user_id=rows[0].get("user_id"))
        _live[sid] = s
        pipeline._sessions[sid] = s
    return s


@router.get("/examples")
async def examples(user: AuthUser = Depends(require_admin)):
    return EXAMPLES


@router.get("/sessions")
async def list_sessions(request: Request, user: AuthUser = Depends(require_admin)):
    rows = await request.app.state.store.select(TABLE, {}, order="updated_at" if request.app.state.store.backend == "supabase" else "created_at", limit=40, token=user.token)
    out = []
    for r in rows:
        d = r.get("data") or {}
        if isinstance(d, str):
            import json

            d = json.loads(d)
        live = _live.get(r["id"])
        out.append({"id": r["id"], "title": (live.title if live else d.get("title")) or "New infrastructure", "status": (live.status.value if live else r.get("status")), "updated_at": r.get("updated_at") or r.get("created_at")})
    return out


@router.post("/sessions")
async def create_session(request: Request, body: Optional[NewSession] = None, user: AuthUser = Depends(require_admin)):
    s = pipeline.new_session()
    s.user_id, s.model = user.id, (body.model if body else "primary")
    _live[s.id] = s
    await _persist(request, s)
    return s.public()


@router.get("/sessions/{sid}")
async def read_session(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    return (await _load(request, sid, user)).public()


@router.delete("/sessions/{sid}")
async def delete_session(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    await _load(request, sid, user)
    await request.app.state.store.delete(TABLE, {"id": sid}, token=user.token)
    _live.pop(sid, None)
    pipeline._sessions.pop(sid, None)
    return {"deleted": sid}


_TRANSIENT = ("Timeout", "Connection", "RateLimit", "APIError", "InternalServer", "APIStatus", "ServiceUnavailable")


def _run_pipeline(s: pipeline.Session, text: str, alias: str, loop, persist) -> None:
    """Runs in a worker thread. Retries once on the other model when the provider, not our logic, failed."""
    other = "secondary" if alias == "primary" else "primary"
    pipeline.handle_message(s, text, build_llm(alias), provisioner_settings.validate_with_terraform)
    if s.status == pipeline.SessionStatus.failed and s.error and any(k in s.error for k in _TRANSIENT):
        s.activity.append({"t": time.time(), "member": "requirements", "kind": "message", "text": "The first model had trouble; retrying with the other one.", "to": None})
        s.history.pop()  # handle_message re-adds the user message
        pipeline.handle_message(s, text, build_llm(other), provisioner_settings.validate_with_terraform)
    s.busy = False
    asyncio.run_coroutine_threadsafe(persist(), loop)


@router.post("/sessions/{sid}/messages", status_code=202)
async def send_message(sid: str, msg: UserMessage, request: Request, tasks: BackgroundTasks, user: AuthUser = Depends(require_admin)):
    s = await _load(request, sid, user)
    if msg.model not in ("primary", "secondary"):
        raise HTTPException(422, "Unknown model")
    if rate_limited(f"iac:{user.id}", 12):
        raise HTTPException(429, "Slow down a little: too many requests in a minute.")
    if s.busy:
        raise HTTPException(409, "The team is still working on your previous message")
    s.busy, s.model = True, msg.model
    if not s.title:
        s.title = msg.content.strip()[:60]
    loop = asyncio.get_running_loop()
    tasks.add_task(_run_pipeline, s, msg.content, msg.model, loop, lambda: _persist(request, s))
    return s.public()


def _run_attachment(s: pipeline.Session, doc, note: str, alias: str, loop, persist) -> None:
    """Worker thread: Dev reads the file, then the normal ask-first pipeline continues from what was read."""
    other = "secondary" if alias == "primary" else "primary"
    used = alias
    try:
        for attempt in (alias, other):
            used = attempt
            try:
                pipeline.read_attachment(s, doc, note, build_llm(attempt))
                break
            except pipeline.StageFailed as exc:
                transient = any(k in str(exc) for k in _TRANSIENT)
                if attempt == alias and transient:
                    continue
                raise
            except Exception as exc:
                if attempt == alias and any(k in type(exc).__name__ for k in _TRANSIENT):
                    continue
                raise
        text = note.strip() or f"Please build the design in the attached file {doc.name}. I have not said which cloud yet."
        pipeline.handle_message(s, text, build_llm(used), provisioner_settings.validate_with_terraform, record_user=False)
        if s.status == pipeline.SessionStatus.failed and s.error and any(k in s.error for k in _TRANSIENT) and used == alias:
            pipeline.handle_message(s, text, build_llm(other), provisioner_settings.validate_with_terraform, record_user=False)
    except Exception as exc:  # reading failed twice: say so plainly instead of leaving the session spinning
        s.status = pipeline.SessionStatus.failed
        s.error = str(exc)
        s.say("agent", f"{exc}. Try again, or describe the design in words and I will build it.")
    finally:
        s.busy = False
        asyncio.run_coroutine_threadsafe(persist(), loop)


@router.get("/attachments/accept")
async def attachments_accept(user: AuthUser = Depends(require_admin)):
    return {"extensions": documents.ACCEPT, "max_mb": documents.MAX_BYTES // 1024 // 1024}


@router.post("/sessions/{sid}/attachments", status_code=202)
async def attach(sid: str, request: Request, tasks: BackgroundTasks, file: UploadFile = File(...), message: str = Form(""), model: str = Form("primary"), user: AuthUser = Depends(require_admin)):
    """Attach an architecture diagram or design document (image, PDF, Word, text). The team reads it, asks what it still needs, then builds it on the cloud you name."""
    s = await _load(request, sid, user)
    if model not in ("primary", "secondary"):
        raise HTTPException(422, "Unknown model")
    if len(message) > 4000:
        raise HTTPException(422, "The note is too long")
    if rate_limited(f"iac:{user.id}", 12):
        raise HTTPException(429, "Slow down a little: too many requests in a minute.")
    if s.busy:
        raise HTTPException(409, "The team is still working on your previous message")
    data = await file.read(documents.MAX_BYTES + 1)
    try:
        doc = await asyncio.to_thread(documents.extract, file.filename or "attachment", data)
    except documents.UnsupportedDocument as exc:
        raise HTTPException(415, str(exc))
    s.busy, s.model = True, model
    if not s.title:
        s.title = (message.strip() or f"Build from {doc.name}")[:60]
    loop = asyncio.get_running_loop()
    tasks.add_task(_run_attachment, s, doc, message, model, loop, lambda: _persist(request, s))
    return s.public()


async def _guard(request: Request, s: pipeline.Session, fn, *args):
    try:
        await asyncio.to_thread(fn, *args)
    except operator.OperatorError as exc:
        await _persist(request, s)
        raise HTTPException(400, str(exc))
    await _persist(request, s)
    return s.public()


@router.post("/sessions/{sid}/plan")
async def plan(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    s = await _load(request, sid, user)
    return await _guard(request, s, operator.plan, s, provisioner_settings.workspace_path)


@router.post("/sessions/{sid}/approve")
async def approve(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    s = await _load(request, sid, user)
    return await _guard(request, s, operator.approve, s, user.email or user.id)


@router.post("/sessions/{sid}/apply")
async def apply(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    s = await _load(request, sid, user)
    return await _guard(request, s, operator.apply, s, provisioner_settings.workspace_path)


@router.get("/sessions/{sid}/download")
async def download(sid: str, request: Request, user: AuthUser = Depends(require_admin)):
    s = await _load(request, sid, user)
    if not s.stack or not s.stack.files:
        raise HTTPException(404, "No files generated yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in s.stack.files:
            z.writestr(f.path, f.content)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="infrastructure-{sid}.zip"'})


# ---------------------------------------------------------------- stacks and drift
internal = APIRouter(prefix="/iac/internal", tags=["internal"])


def _service(x_ingest_token: Optional[str]) -> None:
    if not hmac.compare_digest(x_ingest_token or "", get_settings().ingest_token):
        raise HTTPException(401, "Invalid service token")


@internal.get("/stacks")
async def internal_stacks(x_ingest_token: Optional[str] = Header(default=None)):
    """Stacks this agent applied: what the observability team watches."""
    _service(x_ingest_token)
    return stacks.listing(provisioner_settings.workspace_path)


@internal.post("/stacks/{sid}/drift-check")
async def internal_drift_check(sid: str, x_ingest_token: Optional[str] = Header(default=None)):
    _service(x_ingest_token)
    try:
        return await asyncio.to_thread(stacks.check, provisioner_settings.workspace_path, sid)
    except KeyError:
        raise HTTPException(404, "Unknown stack")


@router.post("/sessions/{sid}/drift/remediate")
async def remediate_drift(sid: str, user: AuthUser = Depends(require_admin)):
    """Admin pressed 'bring it back in line': terraform apply on the stack's workspace."""
    try:
        return await asyncio.to_thread(stacks.remediate, provisioner_settings.workspace_path, sid)
    except KeyError:
        raise HTTPException(404, "Unknown stack")
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
