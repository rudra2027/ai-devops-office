"""App factory shared by every service: CORS, request timing, health, public config, and the static frontend."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Iterable, List

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .apm import install_apm
from .auth import AuthUser, require_user
from .cache import get_cache
from .llm import available_models
from .settings import admin_set, get_settings
from .store import get_store
from .tracing import setup_tracing

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_service_app(*, title: str, agent: str, tables: Iterable[str] = (), features: List[str] = (), startup: Iterable = ()) -> FastAPI:
    """`startup` callables take the app and run (sync or async) after the store is ready."""
    tables = list(tables)
    startup = list(startup)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.tracing = setup_tracing(agent)
        app.state.store = await get_store(tables)
        get_cache()
        for fn in startup:
            r = fn(app)
            if hasattr(r, "__await__"):
                await r
        yield

    app = FastAPI(title=title, lifespan=lifespan)
    s = get_settings()
    app.add_middleware(
        CORSMiddleware, allow_origins=s.cors_origins.split(","), allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Response-Time-ms"]
    )

    @app.middleware("http")
    async def timing(request: Request, call_next):
        t = time.perf_counter()
        resp = await call_next(request)
        resp.headers["X-Response-Time-ms"] = str(int((time.perf_counter() - t) * 1000))
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.method == "GET" and not request.url.path.startswith(("/api", "/iac", "/ops", "/health")):
            resp.headers["Cache-Control"] = "no-cache"  # always revalidate the UI so a redeploy shows up immediately
        return resp

    @app.get("/health")
    async def health():
        st = app.state.store
        return {
            "status": "ok", "agent": agent, "store": st.describe()["backend"], "cache": get_cache().backend,
            "llm_mode": s.llm_mode, "auth_mode": s.auth_mode, "tracing": bool(getattr(app.state, "tracing", False)),
        }

    @app.get("/api/config")
    async def public_config():
        # Everything here is safe to expose: the publishable key is designed to ship to browsers.
        return {
            "agent": agent, "title": title, "features": list(features), "auth_mode": s.auth_mode,
            "supabase_url": s.supabase_url, "supabase_key": s.supabase_publishable_key,
            "models": available_models(), "stt_model": s.stt_model,
            # dev mode only: lets the sign-in card offer one-click "admin" and "customer" test logins
            "dev_admin_email": (sorted(admin_set(s)) or [None])[0] if s.auth_mode == "dev" else None,
        }

    @app.get("/api/me")
    async def me(user: AuthUser = Depends(require_user)):
        return {"id": user.id, "email": user.email, "is_admin": user.is_admin}

    install_apm(app, agent)
    return app


def mount_frontend(app: FastAPI, directory: str) -> None:
    d = Path(directory)
    if d.is_dir():
        app.mount("/", StaticFiles(directory=d, html=True), name="frontend")
