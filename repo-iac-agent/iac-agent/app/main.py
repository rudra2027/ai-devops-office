"""
CLI entry point for the IaC agent.

Usage:
    python -m app.main scan            # one drift scan, then exit
    python -m app.main scan --watch    # scan repeatedly, every scan_interval_seconds
    python -m app.main apply           # one apply-pending pass, then exit
    python -m app.main apply --watch   # poll and apply repeatedly

Run `scan --watch` and `apply --watch` as two separate long-running
processes (two containers/pods in EKS, per Phase 10) rather than one
combined loop — a stuck apply shouldn't block new scans, and vice versa.
"""

import argparse
import logging
import time

from . import apply_loop, drift_scan
from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_scan(watch: bool) -> None:
    if not watch:
        drift_scan.scan_once()
        return
    logger.info("Starting drift scan loop, interval=%ss", settings.scan_interval_seconds)
    while True:
        try:
            drift_scan.scan_once()
        except Exception:
            logger.exception("Drift scan cycle failed — will retry next interval")
        time.sleep(settings.scan_interval_seconds)


def run_apply(watch: bool) -> None:
    if not watch:
        apply_loop.apply_pending_once()
        return
    logger.info("Starting apply loop, interval=%ss", settings.apply_poll_interval_seconds)
    while True:
        try:
            apply_loop.apply_pending_once()
        except Exception:
            logger.exception("Apply cycle failed — will retry next interval")
        time.sleep(settings.apply_poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="IaC agent — drift scan and apply")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan", help="Run a drift scan")
    scan_p.add_argument("--watch", action="store_true", help="Run continuously on an interval")

    apply_p = sub.add_parser("apply", help="Apply approved findings")
    apply_p.add_argument("--watch", action="store_true", help="Run continuously on an interval")

    args = parser.parse_args()

    if args.command == "scan":
        run_scan(args.watch)
    elif args.command == "apply":
        run_apply(args.watch)


if __name__ == "__main__":
    main()
