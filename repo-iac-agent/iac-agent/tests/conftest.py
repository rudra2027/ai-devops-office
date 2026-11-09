import os
import tempfile

os.environ.update({
    "INGEST_TOKEN": "test-ingest",
    "ADMIN_EMAILS": "alice@example.com",
    "AUTH_MODE": "dev", "LLM_MODE": "stub", "STUB_LATENCY_MS": "5", "STORE_BACKEND": "sqlite", "REDIS_URL": "", "OFFICE_URL": "", "OBS_URL": "",
    "LANGSMITH_TRACING": "false", "SQLITE_PATH": os.path.join(tempfile.mkdtemp(), "test.db"), "VALIDATE_WITH_TERRAFORM": "false",
    "WORKSPACE_DIR": tempfile.mkdtemp(),
})
