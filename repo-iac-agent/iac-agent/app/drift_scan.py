"""
Orchestrates one drift-scan cycle: run terraform plan, parse the result,
classify each change, submit findings for anything real. Split into
`build_findings_from_plan_json` (pure, testable — takes plan JSON, returns
finding payloads, no subprocess or network) and `scan_once` (the thin glue
that actually runs terraform and calls the backend).
"""

import logging
from typing import Any, Dict, List

from . import notify_client, terraform_cli
from .config import settings
from .plan_parser import parse_changes
from .policy import classify, enforce_hard_ceiling

logger = logging.getLogger(__name__)


def build_findings_from_plan_json(plan_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pure function: plan JSON in, a list of FindingCreate-shaped dicts
    out. No subprocess, no network — this is what unit tests exercise."""
    findings = []
    for change in parse_changes(plan_json):
        classification = enforce_hard_ceiling(classify(change))
        finding_type = "security" if change.resource_type.startswith("aws_iam") or "security_group" in change.resource_type else "drift"
        findings.append(
            {
                "type": finding_type,
                "resource": change.address,
                "summary": classification.summary,
                "risk_score": classification.risk_score,
                "plan_diff": _format_diff(change),
                "auto_apply": classification.auto_apply,
            }
        )
    return findings


def _format_diff(change) -> str:
    lines = [f"{change.address} ({', '.join(change.actions)})"]
    for attr, values in change.changed_attributes.items():
        lines.append(f"  {attr}: {values['before']!r} -> {values['after']!r}")
    return "\n".join(lines)


def scan_once() -> List[Dict[str, Any]]:
    """Runs a real terraform plan against settings.terraform_dir_path,
    submits any findings to the backend, and returns what was submitted.
    Requires a real terraform binary and AWS credentials — not usable in
    an environment without both. Use build_findings_from_plan_json
    directly (with a fixture) to test the logic without either."""
    terraform_dir = settings.terraform_dir_path
    exit_code, output = terraform_cli.run_plan(terraform_dir)

    if exit_code == terraform_cli.PLAN_ERROR:
        logger.error("terraform plan failed: %s", output)
        raise RuntimeError(f"terraform plan failed in {terraform_dir}: {output}")

    if exit_code == terraform_cli.PLAN_NO_CHANGES:
        logger.info("No drift or pending changes detected.")
        return []

    plan_json = terraform_cli.show_plan_json(terraform_dir)
    findings = build_findings_from_plan_json(plan_json)

    submitted = []
    for finding in findings:
        result = notify_client.submit_finding(finding)
        submitted.append(result)
        logger.info(
            "Submitted finding %s for %s (risk=%s, auto_apply=%s)",
            result.get("id"),
            finding["resource"],
            finding["risk_score"],
            finding["auto_apply"],
        )
    return submitted
