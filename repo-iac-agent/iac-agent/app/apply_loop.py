"""
Polls the backend for findings a human has approved but that haven't been
applied yet, applies each one (targeted terraform apply), and reports the
result back. Deliberately separate from drift_scan.py — scanning and
applying are different responsibilities with different failure modes, and
keeping them as separate loops means a stuck apply can't block new drift
from being detected.
"""

import logging

from . import notify_client, terraform_cli
from .config import settings

logger = logging.getLogger(__name__)


def apply_pending_once() -> int:
    """Applies every currently-approved-but-unapplied finding once.
    Returns how many were processed. Requires a real terraform binary and
    AWS credentials — see terraform_cli.py."""
    terraform_dir = settings.terraform_dir_path
    pending = notify_client.get_findings_awaiting_apply()

    for finding in pending:
        address = finding["resource"]
        logger.info("Applying approved finding %s -> %s", finding["id"], address)
        success, output = terraform_cli.apply_target(terraform_dir, address)
        detail = output[-2000:]  # keep the report readable; full output stays in terraform's own logs
        notify_client.report_apply_result(finding["id"], success=success, detail=detail)
        if success:
            logger.info("Applied %s successfully", address)
        else:
            logger.error("Apply failed for %s: %s", address, detail)

    return len(pending)
