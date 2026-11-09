"""
Runs a headless Locust scenario and saves a summary the Performance panel can show (Services tab).

    python shared/run_loadtest.py support  --users 50 --rate 10 --time 45s
    python shared/run_loadtest.py perf     --users 100 --rate 20 --time 45s

Start the services first (python shared/run_all.py --dev-auth --stub).
"""

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = {
    "support": (ROOT / "repo-support-bot" / "support-bot", "http://127.0.0.1:8000"),
    "perf": (ROOT / "repo-meta-observability" / "meta-observability", "http://127.0.0.1:8400"),
}
OUT = ROOT / "repo-meta-observability" / "meta-observability" / "data" / "loadtests"


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=TARGETS)
    ap.add_argument("--users", type=int, default=50)
    ap.add_argument("--rate", type=int, default=10)
    ap.add_argument("--time", default="45s")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    cwd, host = TARGETS[a.target]
    tmp = Path(tempfile.mkdtemp())
    cmd = [sys.executable, "-m", "locust", "-f", "loadtest/locustfile.py", "--host", host, "--headless", "-u", str(a.users), "-r", str(a.rate), "-t", a.time, "--csv", str(tmp / "r"), "--only-summary"]
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=cwd)
    rows = list(csv.DictReader(open(tmp / "r_stats.csv", encoding="utf-8")))
    agg = next(r for r in rows if r["Name"] == "Aggregated")
    per = {r["Name"]: r for r in rows if r["Name"] != "Aggregated"}
    summary = {
        "users": a.users, "duration": a.time, "requests": int(num(agg["Request Count"])), "failures": int(num(agg["Failure Count"])),
        "throughput_rps": round(num(agg["Requests/s"]), 1), "p50_ms": int(num(agg["50%"])), "p95_ms": int(num(agg["95%"])), "p99_ms": int(num(agg["99%"])),
    }
    for name in ("chat: complete stream", "chat: first token", "ingest (1 call)", "overview 1h"):
        if name in per:
            r = per[name]
            summary[f"{name} p50/p95 (ms)"] = f"{int(num(r['50%']))} / {int(num(r['95%']))}"
    summary["failure rate"] = f"{(summary['failures'] / max(1, summary['requests'])) * 100:.2f}%"
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"name": f"{a.target} · {a.label or 'stub LLM'} · {a.users} users", "when": datetime.now().strftime("%Y-%m-%d %H:%M"), "summary": summary,
              "endpoints": {n: {"requests": int(num(r["Request Count"])), "failures": int(num(r["Failure Count"])), "p50": int(num(r["50%"])), "p95": int(num(r["95%"])), "p99": int(num(r["99%"])), "rps": round(num(r["Requests/s"]), 1)} for n, r in per.items()}}
    (OUT / f"{datetime.now():%Y%m%d-%H%M%S}-{a.target}-{a.users}u.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
