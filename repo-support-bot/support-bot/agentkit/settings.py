"""
One settings object for every agent. Values come from the process environment, then from the first `.env` found
walking up from the working directory (the shared secrets file lives at the multiagent root, outside every repo).
"""

from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_files() -> List[str]:
    found = []
    here = Path.cwd().resolve()
    for p in [here, *here.parents][:5]:
        f = p / ".env"
        if f.is_file():
            found.append(str(f))
    return list(reversed(found))  # nearest .env wins (pydantic-settings: later files override earlier)


class KitSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_env_files(), env_file_encoding="utf-8", extra="ignore")

    # --- LLMs, all through OpenRouter ---
    openrouter_api_key: Optional[str] = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_primary_model: str = "openai/gpt-6.1-sol"
    llm_secondary_model: str = "anthropic/claude-sonnet-5.5"
    stt_model: str = "google/gemini-3.5-flash"
    # live = real models; stub = canned replies with simulated latency (load tests of our own stack)
    llm_mode: Literal["live", "stub"] = "live"
    stub_latency_ms: int = 350

    # --- Supabase: auth + database ---
    supabase_url: Optional[str] = None
    supabase_publishable_key: Optional[str] = None
    # supabase = real JWT validation against Supabase; dev = accept "dev:<email>" tokens (local tests only)
    auth_mode: Literal["supabase", "dev"] = "supabase"
    store_backend: Literal["auto", "supabase", "sqlite"] = "auto"
    sqlite_path: str = "data/agent.db"

    # --- Redis (rate limits, caches). Falls back to in-process memory when unreachable ---
    redis_url: Optional[str] = None

    # --- LangSmith ---
    langsmith_tracing: bool = False
    langsmith_api_key: Optional[str] = None
    langsmith_project: str = "four-agent"

    # --- Cross-agent reporting ---
    office_url: str = ""
    obs_url: str = ""
    ingest_token: str = "dev-ingest-token"

    # --- Roles: one admin (comma-separated emails allowed). Everyone else is a customer. ---
    admin_emails: str = ""
    cicd_webhook_token: str = ""  # empty = the CI/CD webhook is disabled

    # --- Limits ---
    rate_limit_per_minute: int = 30
    cors_origins: str = "*"


def admin_set(s: "KitSettings") -> set:
    return {e.strip().lower() for e in s.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> KitSettings:
    return KitSettings()
