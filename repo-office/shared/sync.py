"""
Copies the shared pieces into every service so each repo stays self-contained and deployable on its own:

    shared/agentkit  ->  <repo>/<service>/agentkit
    shared/ui        ->  <repo>/<service>/frontend/kit

Run after editing anything under shared/:   python shared/sync.py
"""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the multiagent folder
SERVICES = {
    "support-bot": ROOT / "repo-support-bot" / "support-bot",
    "iac-agent": ROOT / "repo-iac-agent" / "iac-agent",
    "cicd-agent": ROOT / "repo-cicd-agent" / "cicd-agent",
    "meta-observability": ROOT / "repo-meta-observability" / "meta-observability",
    "office": ROOT / "repo-office" / "office",
}
NO_UI = {"office"}  # the office visualization keeps its own styles
SHARED = Path(__file__).resolve().parent


def copy(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


if __name__ == "__main__":
    for name, svc in SERVICES.items():
        if not svc.is_dir():
            print(f"skip {name}: {svc} missing")
            continue
        copy(SHARED / "agentkit", svc / "agentkit")
        if (SHARED / "ui").is_dir() and name not in NO_UI:
            (svc / "frontend").mkdir(exist_ok=True)
            copy(SHARED / "ui", svc / "frontend" / "kit")
        print(f"synced {name}")
