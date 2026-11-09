import os
import tempfile

os.environ.update({
    "INGEST_TOKEN": "test-ingest",
    "ADMIN_EMAILS": "alice@example.com",
    "AUTH_MODE": "dev", "LLM_MODE": "stub", "STORE_BACKEND": "sqlite", "REDIS_URL": "", "OFFICE_URL": "", "OBS_URL": "",
    "LANGSMITH_TRACING": "false", "SQLITE_PATH": os.path.join(tempfile.mkdtemp(), "test.db"),
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import review as review_mod  # noqa: E402
from app.main import app  # noqa: E402


async def fake_review(diff, alias="primary", context=""):
    """Stands in for the LLM; the deterministic secret scan still runs exactly as in production."""
    res = review_mod.ReviewSummary(title="Fake review", summary=["A change."], risk="low", recommend_approval=True,
                                   findings=[review_mod.Finding(severity="warning", file="a.py", issue="Consider a test.")] if "TODO" in diff else [])
    res.findings += review_mod.deterministic_findings(diff)
    if any(f.severity == "blocker" for f in res.findings):
        res.recommend_approval, res.risk = False, "high"
    return res


@pytest.fixture(scope="session")
def client():
    from app import runs

    runs.review_diff = fake_review
    with TestClient(app) as c:
        yield c


def auth(email: str = "alice@example.com") -> dict:
    return {"Authorization": f"Bearer dev:{email}"}
