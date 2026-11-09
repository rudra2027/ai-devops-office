from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Non-secret config. Same split as chatbot-app/backend — see its
    config.py/secrets.py for the reasoning."""

    # Directory containing the Terraform root to scan/apply — points at
    # infra/environments/dev by default.
    # Relative to the CURRENT WORKING DIRECTORY when the CLI runs, not to
    # this file's location — Path.resolve() below resolves against cwd.
    # Assumes you run `python -m app.main ...` from the repo root, where
    # this and infra/ are siblings.
    terraform_dir: str = "infra/environments/dev"

    # The chatbot backend's ops API — findings get POSTed here.
    backend_url: str = "http://localhost:8000"

    # How often the drift scanner runs, in seconds.
    scan_interval_seconds: int = 900  # 15 minutes

    # How often the apply loop polls for human-approved findings.
    apply_poll_interval_seconds: int = 60

    # Risk score threshold (0-100) at or above which a finding always
    # requires human approval, regardless of what policy.py's rules say —
    # a hard ceiling under the rules, not instead of them.
    high_risk_threshold: int = 70

    debug: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def terraform_dir_path(self) -> Path:
        return Path(self.terraform_dir).resolve()


settings = Settings()
