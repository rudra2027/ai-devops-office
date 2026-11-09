"""
Starts every service locally and stops them together on Ctrl+C.

    python shared/run_all.py                 real Supabase auth, real models
    python shared/run_all.py --dev-auth      accept "dev:<email>" tokens (local QA only)
    python shared/run_all.py --stub          canned LLM replies, no credits spent (load tests)

Admin console (the Agent Office) opens automatically at http://localhost:8200.
Customers use only the support chat at http://localhost:8000.
Ports: support 8000, iac 8100, office 8200, cicd 8300, performance 8400.
"""

import argparse
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = [
    ("perf", ROOT / "repo-meta-observability" / "meta-observability", "app.main:app", 8400),
    ("support", ROOT / "repo-support-bot" / "support-bot", "app.main:app", 8000),
    ("iac", ROOT / "repo-iac-agent" / "iac-agent", "api.main:app", 8100),
    ("cicd", ROOT / "repo-cicd-agent" / "cicd-agent", "app.main:app", 8300),
    ("office", ROOT / "repo-office" / "office", "hub.main:app", 8200),
]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-auth", action="store_true")
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--no-open", action="store_true", help="do not open the admin console in a browser")
    a = ap.parse_args()
    env = dict(os.environ)
    if a.dev_auth:
        env["AUTH_MODE"] = "dev"
        # A fresh clone has no .env. Give local dev mode a working admin login and a random service token
        # (so the services never run on the built-in default token), unless you already set your own.
        root_env = (ROOT / ".env").read_text(encoding="utf-8", errors="ignore") if (ROOT / ".env").exists() else ""
        if "ADMIN_EMAILS" not in env and "ADMIN_EMAILS=" not in root_env:
            env["ADMIN_EMAILS"] = "admin@example.com"
        if "INGEST_TOKEN" not in env and "INGEST_TOKEN=" not in root_env:
            import secrets
            env["INGEST_TOKEN"] = secrets.token_hex(16)
    if a.stub:
        env["LLM_MODE"] = "stub"
    procs = []
    logs = ROOT / "repo-office" / "logs"
    logs.mkdir(exist_ok=True)
    for name, cwd, app, port in SERVICES:
        f = open(logs / f"{name}.log", "w")
        procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--port", str(port)], cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT))
        print(f"started {name} on http://localhost:{port}")
    print("\nAdmin console (Agent Office):  http://localhost:8200\nCustomer support chat:         http://localhost:8000\n")
    if not a.no_open:
        time.sleep(4)
        webbrowser.open("http://localhost:8200")
    try:
        while any(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            p.terminate()
