"""
Deterministic, cloud-neutral checks on generated Terraform. These run no
matter what the LLM reviewer says — a model can't talk its way past them.
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Tuple

from .schemas import ReviewFinding, TerraformFile

# (regex, severity, message)
_PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    (re.compile(r'(?i)\b(password|secret|token|api[_-]?key|access[_-]?key)\b\s*=\s*"(?!\$\{)(?!var\.)[^"\s]{6,}"'),
     "blocker", "Looks like a hard-coded credential. Use a variable (sensitive = true) or a secrets service."),
    (re.compile(r'AKIA[0-9A-Z]{16}'), "blocker", "AWS-style access key id in source."),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'), "blocker", "Private key material in source."),
    (re.compile(r'0\.0\.0\.0/0|::/0'), "warning", "Open to the whole internet. Confirm this is intended and not for admin ports (22, 3389, DB ports)."),
    (re.compile(r'(?i)public[_-]?(access|read|network_access)\w*\s*=\s*(true|"?enabled"?)'), "warning", "Public access enabled on a resource."),
    (re.compile(r'(?i)\b(encrypt\w*|encryption\w*)\s*=\s*(false|"?disabled"?)'), "warning", "Encryption explicitly disabled."),
]


def safe_path(path: str) -> str:
    """Reject absolute paths and traversal; generated files must stay in the workspace."""
    p = PurePosixPath(path.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.name or re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"Unsafe file path from model: {path!r}")
    if p.suffix not in {".tf", ".tfvars", ".json", ".sh", ".yaml", ".yml", ".tpl", ".md", ".txt"}:
        raise ValueError(f"File type not allowed: {path!r}")
    return str(p)


def scan_for_risky_patterns(files: List[TerraformFile]) -> List[ReviewFinding]:
    findings = []
    for f in files:
        for lineno, line in enumerate(f.content.splitlines(), start=1):
            if line.lstrip().startswith(("#", "//")):
                continue
            for rx, severity, message in _PATTERNS:
                if rx.search(line):
                    findings.append(
                        ReviewFinding(severity=severity, resource=f"{f.path}:{lineno}", message=message)
                    )
    return findings


def validate_terraform(files: List[TerraformFile], use_terraform: bool = True) -> Tuple[bool, str]:
    """HCL syntax check via python-hcl2 (always), then `terraform validate`
    when a binary is available. Returns (ok, message the LLM can act on)."""
    import hcl2  # imported lazily so the rest of the package works without it

    problems = []
    for f in files:
        if not f.path.endswith(".tf"):
            continue
        try:
            hcl2.loads(f.content)
        except Exception as exc:  # hcl2 raises lark errors of several types
            problems.append(f"{f.path}: {str(exc)[:400]}")
    if problems:
        return False, "HCL syntax errors:\n" + "\n".join(problems)

    if use_terraform and shutil.which("terraform"):
        with tempfile.TemporaryDirectory() as tmp:
            for f in files:
                target = Path(tmp) / safe_path(f.path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f.content, encoding="utf-8")
            init = subprocess.run(
                ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
                cwd=tmp, capture_output=True, text=True, timeout=600,
            )
            if init.returncode != 0:
                return False, "terraform init failed:\n" + (init.stdout + init.stderr)[-1500:]
            val = subprocess.run(
                ["terraform", "validate", "-no-color"], cwd=tmp, capture_output=True, text=True, timeout=120
            )
            if val.returncode != 0:
                return False, "terraform validate failed:\n" + (val.stdout + val.stderr)[-1800:]
            return True, "terraform validate passed"
    return True, "HCL syntax OK (terraform binary not found, so provider schema was not checked)"
