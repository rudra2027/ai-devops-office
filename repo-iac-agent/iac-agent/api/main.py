from pathlib import Path

from agentkit.app import create_service_app, mount_frontend

from .findings import router as findings_router
from .sessions import internal as internal_router
from .sessions import router as sessions_router

app = create_service_app(title="Infrastructure Agent", agent="iac", tables=["iac_sessions"], features=["provision", "findings", "download"])
app.include_router(sessions_router)
app.include_router(findings_router)
app.include_router(internal_router)
mount_frontend(app, str(Path(__file__).resolve().parent.parent / "frontend"))
