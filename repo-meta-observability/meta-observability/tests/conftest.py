import os
import tempfile

os.environ.update({
    "ADMIN_EMAILS": "alice@example.com",
    "AUTH_MODE": "dev", "LLM_MODE": "stub", "STORE_BACKEND": "sqlite", "REDIS_URL": "", "OFFICE_URL": "", "OBS_URL": "",
    "LANGSMITH_TRACING": "false", "LANGSMITH_API_KEY": "", "SQLITE_PATH": os.path.join(tempfile.mkdtemp(), "test.db"), "INGEST_TOKEN": "test-token",
})
