from typing import Optional

from pydantic_settings import BaseSettings


class Secrets(BaseSettings):
    """
    Same reasoning as chatbot-app/backend/app/secrets.py: local dev reads
    from .env (gitignored, never in any image); in EKS this comes from a
    K8s Secret sourced from AWS Secrets Manager.

    AWS credentials themselves are NOT handled here — this agent runs as a
    pod with its own Pod Identity Association, so boto3/the AWS provider
    pick up credentials automatically from the environment. Never put an
    AWS access key in this file.
    """

    # Must match AGENT_API_TOKEN on the chatbot backend. Optional locally
    # (backend accepts unauthenticated agent calls if its own token is
    # unset) — set both once this leaves localhost.
    agent_api_token: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


secrets = Secrets()
