from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from agentkit.llm import get_chat_model


class ProvisionerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    workspace_dir: str = "workspaces"
    validate_with_terraform: bool = True

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir).resolve()


provisioner_settings = ProvisionerSettings()


def build_llm(alias: str = "primary"):
    """Plain chat model (no fallback wrapper) because each stage binds its own tools. Model fallback is handled by the caller."""
    return get_chat_model(alias, temperature=0, agent="iac", fallback=False)
