"""
Thin wrapper around `terraform` subprocess calls. Deliberately minimal —
all the actual logic (parsing, classification) lives in plan_parser.py and
policy.py, which take/return plain data and don't touch subprocess at all.
That split is what makes this whole agent testable without a terraform
binary or AWS credentials in the loop: everything except this file.
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

# terraform plan's documented exit codes with -detailed-exitcode:
#   0 = no changes, 1 = error, 2 = changes present
PLAN_NO_CHANGES = 0
PLAN_ERROR = 1
PLAN_CHANGES_PRESENT = 2


def run_plan(terraform_dir: Path, plan_out: str = "tfplan") -> Tuple[int, str]:
    """Runs `terraform plan -detailed-exitcode -out=<plan_out>`. Returns
    (exit_code, combined stdout+stderr). Caller decides what to do with
    each exit code — this function doesn't raise on a non-zero exit,
    since 1 and 2 are both meaningful, expected outcomes here, not just 0."""
    result = subprocess.run(
        ["terraform", "plan", "-detailed-exitcode", f"-out={plan_out}"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def show_plan_json(terraform_dir: Path, plan_out: str = "tfplan") -> Dict[str, Any]:
    """Runs `terraform show -json <plan_out>` and parses the result."""
    result = subprocess.run(
        ["terraform", "show", "-json", plan_out],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def apply_target(terraform_dir: Path, resource_address: str) -> Tuple[bool, str]:
    """Runs a targeted `terraform apply -target=<address> -auto-approve`.
    Only ever called for a finding a human has already approved — this is
    not where approval is decided, just where it's executed."""
    result = subprocess.run(
        ["terraform", "apply", "-auto-approve", f"-target={resource_address}"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
    )
    success = result.returncode == 0
    output = result.stdout + result.stderr
    return success, output
