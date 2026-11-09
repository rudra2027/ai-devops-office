import asyncio
import hmac
import json
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agentkit.apm import install_apm
from agentkit.auth import AuthUser, admin_from_request, require_admin, require_user
from agentkit.llm import available_models
from agentkit.settings import admin_set, get_settings

from .bus import bus
from .demo import demo_seconds, play_demo
from .models import AgentEvent, Roster
from .roster import MEMBER_IDS, TEAMS

app = FastAPI(title="Agent Office Hub")
install_apm(app, "office")

# Local dev only — tighten once the frontend has a real origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_demo_task = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
def public_config() -> dict:
    s = get_settings()
    return {"agent": "office", "auth_mode": s.auth_mode, "supabase_url": s.supabase_url, "supabase_key": s.supabase_publishable_key,
            "dev_admin_email": (sorted(admin_set(s)) or [None])[0] if s.auth_mode == "dev" else None}


@app.get("/api/me")
async def me(user: AuthUser = Depends(require_user)) -> dict:
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


@app.get("/roster", response_model=Roster)
def roster(_: AuthUser = Depends(require_admin)) -> Roster:
    return Roster(teams=TEAMS, members=bus.snapshots())


# async on purpose: bus.publish touches asyncio queues and must run on the loop.
@app.post("/events", response_model=AgentEvent)
async def post_event(event: AgentEvent, x_ingest_token: Optional[str] = Header(default=None)) -> AgentEvent:
    # Only our own services may write to the office floor.
    if not hmac.compare_digest(x_ingest_token or "", get_settings().ingest_token):
        raise HTTPException(401, "Invalid ingest token")
    if (event.team, event.member) not in MEMBER_IDS:
        raise HTTPException(status_code=422, detail=f"Unknown colleague {event.team}/{event.member}")
    return bus.publish(event)


@app.get("/events", response_model=List[AgentEvent])
def list_events(since: int = 0, _: AuthUser = Depends(require_admin)) -> List[AgentEvent]:
    return bus.since(since)


@app.get("/stream")
async def stream(request: Request, last_event_id: int = 0, _: AuthUser = Depends(admin_from_request)):
    """Server-sent events. Replays anything after last_event_id (the browser
    sends it automatically as Last-Event-ID on reconnect), then goes live."""
    header_id = request.headers.get("last-event-id")
    if header_id and header_id.isdigit():
        last_event_id = int(header_id)

    queue = bus.subscribe()
    backlog = bus.since(last_event_id)

    async def gen():
        try:
            seen = last_event_id
            for e in backlog:
                seen = e.id
                yield f"id: {e.id}\ndata: {e.model_dump_json()}\n\n"
            while True:
                try:
                    e = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
                    continue
                if e.id <= seen:
                    continue
                seen = e.id
                yield f"id: {e.id}\ndata: {e.model_dump_json()}\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/demo/start")
async def demo_start(_: AuthUser = Depends(require_admin)) -> dict:
    global _demo_task
    if _demo_task is not None and not _demo_task.done():
        return {"status": "already_running"}
    _demo_task = asyncio.create_task(play_demo())
    return {"status": "started", "seconds": round(demo_seconds())}


# Serve the office UI from the same origin as the hub.
_frontend = Path(__file__).resolve().parent.parent / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
