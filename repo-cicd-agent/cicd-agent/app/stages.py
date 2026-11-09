"""
Pipeline stages. Each runs for real when its tool is available and otherwise reports `skipped` with the reason, so the UI
never pretends something happened. Stages return (status, log) where status is passed | failed | skipped.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .review import deterministic_findings

TIMEOUT = int(os.environ.get("CICD_STAGE_TIMEOUT", "180"))


def _run(cmd, cwd: Path, timeout: int = TIMEOUT) -> Tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-6000:]
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s"
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"


def run_tests(repo: Optional[Path], command: Optional[str]) -> Tuple[str, str]:
    if repo is None:
        return "skipped", "No repository path was given (a pasted diff has nothing to execute)."
    cmd = command.split() if command else None
    if cmd is None:
        if (repo / "pytest.ini").exists() or (repo / "tests").is_dir():
            cmd = ["python", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"]
        elif (repo / "package.json").exists() and shutil.which("npm"):
            cmd = ["npm", "test", "--silent"]
        else:
            return "skipped", "No test suite detected (looked for pytest config, tests/, package.json)."
    code, out = _run(cmd, repo)
    return ("passed" if code == 0 else "failed"), f"$ {' '.join(cmd)}\n{out}"


def run_scan(repo: Optional[Path], diff: str) -> Tuple[str, str]:
    lines = []
    blockers = [f for f in deterministic_findings(diff) if f.severity == "blocker"]
    for f in blockers:
        lines.append(f"[secret] {f.file}:{f.line} {f.issue}")
    status = "failed" if blockers else "passed"
    lines.insert(0, f"Secret scan on added lines: {'FAILED' if blockers else 'clean'}")
    if repo is not None and shutil.which("trivy"):
        code, out = _run(["trivy", "fs", "--quiet", "--severity", "HIGH,CRITICAL", "--exit-code", "1", str(repo)], repo)
        lines.append(f"\n$ trivy fs ...\n{out}")
        if code not in (0,):
            status = "failed"
    else:
        lines.append("Trivy: skipped (not installed or no repository path).")
    lines.append("SonarQube: skipped (SONAR_HOST_URL / SONAR_TOKEN not configured)." if not os.environ.get("SONAR_TOKEN") else "SonarQube: configured (analysis not wired yet).")
    return status, "\n".join(lines)


def run_build(repo: Optional[Path], tag: str) -> Tuple[str, str]:
    if os.environ.get("CICD_ENABLE_DOCKER", "").lower() not in ("1", "true", "yes"):
        return "skipped", "Image builds are disabled. Set CICD_ENABLE_DOCKER=true on a machine with Docker to enable them."
    if repo is None or not (repo / "Dockerfile").exists():
        return "skipped", "No Dockerfile found."
    if not shutil.which("docker"):
        return "skipped", "docker is not installed."
    code, out = _run(["docker", "build", "-t", tag, "."], repo, timeout=900)
    return ("passed" if code == 0 else "failed"), out


def run_deploy(tag: str) -> Tuple[str, str]:
    if not os.environ.get("ARGOCD_SERVER"):
        return "skipped", "No deploy target configured (ARGOCD_SERVER is not set), so no blue/green rollout was started."
    return "skipped", "ArgoCD is configured but the rollout adapter is not implemented yet."


def safe_repo(path: str, roots) -> Path:
    """Only repositories under an allowed root may be read; stops the API being used to browse the file system."""
    p = Path(path).expanduser().resolve()
    if not any(p == r or r in p.parents for r in roots):
        raise PermissionError("That path is outside the allowed workspace roots")
    if not (p / ".git").exists():
        raise FileNotFoundError("Not a git repository")
    return p


def git_diff(repo: Path, base: str, head: str) -> str:
    for ref in (base, head):
        if not re.fullmatch(r"[\w./~^@{}-]{1,80}", ref) or ref.startswith("-"):
            raise ValueError("Invalid git ref")
    code, out = _run(["git", "diff", "--no-color", "--unified=3", f"{base}..{head}"], repo, timeout=30)
    if code != 0:
        raise RuntimeError(out[-300:])
    return out
