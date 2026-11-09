"""Creates the labels and starter issues from docs/good-first-issues.md using the GitHub CLI.

    gh auth login
    python scripts/seed_issues.py [owner/repo]

Safe to re-run: issues whose title already exists are skipped.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = sys.argv[1] if len(sys.argv) > 1 else "rudra2027/ai-devops-office"
DOC = Path(__file__).resolve().parents[1] / "docs" / "good-first-issues.md"
COLORS = {"good first issue": "7057ff", "help wanted": "008672", "bug": "d73a4a", "enhancement": "a2eeef", "frontend": "fbca04", "docs": "0075ca"}


def gh(*args, check=True):
    return subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True, check=check)


issues, cur = [], None
for line in DOC.read_text(encoding="utf-8").splitlines():
    if line.startswith("## "):
        cur = {"title": line[3:].strip(), "labels": [], "body": []}
        issues.append(cur)
    elif cur is not None:
        m = re.match(r"labels:\s*(.+)", line)
        if m and not cur["labels"]:
            cur["labels"] = [x.strip() for x in m.group(1).split(",")]
        else:
            cur["body"].append(line)

for lab in {l for i in issues for l in i["labels"]} | set(COLORS):
    color = COLORS.get(lab, "1d76db" if lab.startswith("area:") else "ededed")
    gh("label", "create", lab, "--color", color, "--force", check=False)

listing = gh("issue", "list", "--state", "all", "--limit", "200", "--json", "title", check=False).stdout or "[]"
existing = {i["title"] for i in json.loads(listing)}
for i in issues:
    if i["title"] in existing:
        print("skip (exists):", i["title"])
        continue
    args = ["issue", "create", "--title", i["title"], "--body", "\n".join(i["body"]).strip()]
    for lab in i["labels"]:
        args += ["--label", lab]
    r = gh(*args, check=False)
    print(("created: " if r.returncode == 0 else "FAILED: ") + i["title"], r.stdout.strip() or r.stderr.strip())
