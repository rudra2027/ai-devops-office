import os
import tempfile

# Must be set before agentkit.settings is first imported: tests run offline with a canned model and a throwaway database.
os.environ.update({
    "ADMIN_EMAILS": "admin@example.com",
    "AUTH_MODE": "dev", "LLM_MODE": "stub", "STUB_LATENCY_MS": "5", "STORE_BACKEND": "sqlite", "REDIS_URL": "", "OFFICE_URL": "", "OBS_URL": "",
    "LANGSMITH_TRACING": "false", "SQLITE_PATH": os.path.join(tempfile.mkdtemp(), "test.db"), "RATE_LIMIT_PER_MINUTE": "1000",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


def auth(email: str = "alice@example.com") -> dict:
    return {"Authorization": f"Bearer dev:{email}"}
