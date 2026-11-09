"""LangSmith tracing: LangChain reads these env vars automatically, so configuring them once covers every call."""

import os

from .settings import get_settings


def setup_tracing(agent: str) -> bool:
    s = get_settings()
    if not (s.langsmith_tracing and s.langsmith_api_key):
        return False
    for prefix in ("LANGSMITH", "LANGCHAIN"):
        os.environ[f"{prefix}_API_KEY"] = s.langsmith_api_key
        os.environ[f"{prefix}_PROJECT"] = s.langsmith_project
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    return True


def run_config(agent: str, **meta) -> dict:
    """Tags every trace with the agent so LangSmith can be filtered per team."""
    return {"tags": [agent], "metadata": {"agent": agent, **meta}}
