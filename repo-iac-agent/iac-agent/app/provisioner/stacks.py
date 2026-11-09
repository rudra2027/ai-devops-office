"""
Registry of stacks the Infrastructure agent has applied, plus drift checks against them.

The registry is a small JSON file next to the workspaces, so monitoring keeps working after a restart and does not depend on
database permissions. A drift check is `terraform plan` on the stack's workspace: no changes means in sync; changes mean the
real infrastructure no longer matches the code (or the code moved on). Findings reuse the existing plan parser and risk
policy, so tags-only changes score low and IAM / network / stateful changes score high.
"""

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import office_client

_lock = threading.Lock()


def _file(root: Path) -> Path:
    return root / "_stacks.json"


def load(root: Path) -> Dict[str, Dict[str, Any]]:
    f = _file(root)
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(root: Path, data: Dict[str, Dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _file(root).write_text(json.dumps(data, indent=1), encoding="utf-8")


def register(root: Path, session) -> None:
    """Called after a successful apply so the platform starts watching the stack."""
    arch = session.architecture
    entry = {
        "id": session.id, "title": session.title or "Untitled stack", "applied_at": time.time(), "workspace": str(root / session.id),
        "cloud": arch.provider.cloud if arch else None, "provider": arch.provider.terraform_source if arch else None,
        "region": arch.region if arch else None, "auth_env_vars": arch.provider.auth_env_vars if arch else [],
        "resources": sum(len(m.resource_types) for m in arch.mappings) if arch else 0,
        "drift": {"status": "unchecked", "checked_at": None, "findings": []},
    }
    with _lock:
        data = load(root)
        data[session.id] = entry
        save(root, data)


def listing(root: Path) -> List[Dict[str, Any]]:
    return sorted(load(root).values(), key=lambda s: s["applied_at"], reverse=True)


def _cannot(reason: str, fix: str) -> Dict[str, Any]:
    return {"status": "cannot_check", "checked_at": time.time(), "findings": [], "error": reason, "how_to_fix": fix}


def _creds_hint(out: str, stack: Dict[str, Any]) -> Optional[str]:
    low = out.lower()
    if any(k in low for k in ("credential", "unauthorized", "authentication", "api token", "401", "403", "no valid", "access denied")):
        vars_ = ", ".join(stack.get("auth_env_vars") or []) or "the provider's credential variables"
        return f"The cloud rejected the credentials. Set {vars_} in the environment of the Infrastructure agent and restart it."
    return None


def check(root: Path, stack_id: str) -> Dict[str, Any]:
    """Runs a drift check and records the result in the registry."""
    from .. import drift_scan, terraform_cli  # imported here: they pull in the CLI settings

    data = load(root)
    stack = data.get(stack_id)
    if stack is None:
        raise KeyError(stack_id)
    ws = Path(stack["workspace"])
    if not ws.is_dir():
        result = _cannot(f"The workspace folder {ws} is missing.", "Restore the workspace, or re-create the stack from its session.")
    elif shutil.which("terraform") is None:
        result = _cannot("Terraform is not installed on the machine that runs the Infrastructure agent, so drift cannot be checked.",
                         "Install Terraform 1.5 or newer and make sure it is on PATH, then check again.")
    else:
        try:
            code, out = terraform_cli.run_plan(ws, "drift.tfplan")
        except Exception as exc:
            code, out = 1, f"{type(exc).__name__}: {exc}"
        if code == terraform_cli.PLAN_NO_CHANGES:
            result = {"status": "in_sync", "checked_at": time.time(), "findings": []}
        elif code == terraform_cli.PLAN_CHANGES_PRESENT:
            try:
                findings = drift_scan.build_findings_from_plan_json(terraform_cli.show_plan_json(ws, "drift.tfplan"))
            except Exception as exc:
                findings = [{"resource": "(unparsed plan)", "summary": f"Changes detected but the plan could not be parsed: {exc}", "risk_score": 50, "plan_diff": out[-600:], "auto_apply": False, "type": "drift"}]
            result = {"status": "drift", "checked_at": time.time(), "findings": findings}
        else:
            result = _cannot("terraform plan failed: " + out.strip()[-300:], _creds_hint(out, stack) or "Open the workspace and run terraform plan to see the full error.")
    with _lock:
        data = load(root)
        if stack_id in data:
            data[stack_id]["drift"] = result
            save(root, data)
    status = result["status"]
    if status == "drift":
        office_client.emit("drift", "message", f"Drift on {stack['title']}: {len(result['findings'])} difference(s).", state="waiting")
    elif status == "in_sync":
        office_client.emit("drift", "message", f"{stack['title']} matches its code.", state="idle")
    return {**stack, "drift": result}


def remediate(root: Path, stack_id: str) -> Dict[str, Any]:
    """Puts reality back in line with the code (terraform apply). Only ever called after an explicit admin confirmation."""
    stack = load(root).get(stack_id)
    if stack is None:
        raise KeyError(stack_id)
    if shutil.which("terraform") is None:
        raise RuntimeError("Terraform is not installed on the machine that runs the Infrastructure agent.")
    import subprocess

    office_client.emit("operator", "inbound", f"Remediating drift on {stack['title']} (approved by admin).", state="working")
    r = subprocess.run(["terraform", "apply", "-input=false", "-auto-approve", "-no-color"], cwd=stack["workspace"], capture_output=True, text=True, timeout=3600)
    ok = r.returncode == 0
    office_client.emit("operator", "done" if ok else "error", "Drift remediated." if ok else (r.stdout + r.stderr)[-300:], state="idle" if ok else "error")
    if not ok:
        raise RuntimeError((r.stdout + r.stderr)[-500:])
    return check(root, stack_id)
