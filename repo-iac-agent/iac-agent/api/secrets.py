from typing import Optional

from pydantic_settings import BaseSettings


class Secrets(BaseSettings):
    """
    This is the API service's copy of the shared agent token — the CLI
    (../app/secrets.py) has its own copy of the same setting, since they're
    two separate deployable processes/images even though they're one
    logical agent. Both must be set to the SAME value when deployed; there
    is no code sharing between them, only a shared env var name/value at
    deploy time.

    No default value, same reasoning as everywhere else in this project:
    None means "no auth enforced" (fine for local dev), an explicit value
    means every write endpoint checks it.
    """

    agent_api_token: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


secrets = Secrets()
