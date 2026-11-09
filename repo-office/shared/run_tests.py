"""Runs every service's test suite (stub LLM, no network, no keys). Exit code is non-zero if any suite fails.

    python repo-office/shared/run_tests.py
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITES = [
    "repo-office/shared", "repo-support-bot/support-bot", "repo-iac-agent/iac-agent",
    "repo-cicd-agent/cicd-agent", "repo-meta-observability/meta-observability", "repo-office/office",
]

failed = []
for s in SUITES:
    print(f"\n=== {s}", flush=True)
    env = dict(os.environ, AUTH_MODE="dev", LLM_MODE="stub")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT / s, env=env)
    if r.returncode != 0:
        failed.append(s)
print("\nALL SUITES PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
