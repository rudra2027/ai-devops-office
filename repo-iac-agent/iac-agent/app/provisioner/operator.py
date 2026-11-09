"""
Ira: runs terraform plan and apply for a designed stack. Credentials come
from the process environment (provider-specific variables, Pod Identity, etc.)
and are never visible to any LLM. Apply is refused unless a human approved
exactly the plan that was produced.
"""

import subprocess
from pathlib import Path
from typing import Tuple

from .. import office_client
from . import checks
from . import attention as attention_mod
from .pipeline import Session
from .schemas import SessionStatus


class OperatorError(RuntimeError):
    pass


def _emit(kind: str, text: str, **kw) -> None:
    from .pipeline import _emit as session_emit  # also lands in the session's activity feed

    session_emit("operator", kind, text, **kw)


def _run(args, cwd: Path, timeout: int) -> Tuple[int, str]:
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def write_workspace(session: Session, root: Path) -> Path:
    if session.stack is None:
        raise OperatorError("No generated stack yet")
    ws = root / session.id
    ws.mkdir(parents=True, exist_ok=True)
    for old in ws.glob("*.tf"):
        old.unlink()
    for f in session.stack.files:
        target = ws / checks.safe_path(f.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content, encoding="utf-8")
    return ws


def plan(session: Session, root: Path) -> Session:
    from .pipeline import _current

    _current.set(session)
    if session.status not in (SessionStatus.ready_for_plan, SessionStatus.planned):
        raise OperatorError(f"Cannot plan while status is {session.status.value}")
    if session.review is None or not session.review.approved_for_plan:
        raise OperatorError("Review has blockers; fix the design first")
    _emit("inbound", "Plan requested.", state="working")
    ws = write_workspace(session, root)
    try:
        _emit("tool_call", "terraform init")
        code, out = _run(["terraform", "init", "-input=false", "-no-color"], ws, 900)
        if code != 0:
            raise OperatorError("terraform init failed:\n" + out[-1500:])
        _emit("tool_call", "terraform plan -out=tfplan")
        code, out = _run(["terraform", "plan", "-input=false", "-no-color", "-detailed-exitcode", "-out=tfplan"], ws, 900)
        if code == 1:
            raise OperatorError("terraform plan failed:\n" + out[-1500:])
    except FileNotFoundError:
        raise OperatorError("terraform is not installed on the machine running the agent")
    except OperatorError as exc:
        session.error = str(exc)
        _emit("error", str(exc)[:500], state="error")
        session.attention = attention_mod.compute(session) + [{"id": "plan_error", "kind": "error", "severity": "blocker", "member": "operator", "title": "The plan could not run",
                                                               "detail": str(exc)[:300], "how_to_fix": "Fix the cause above (usually Terraform or credentials), then press Run plan again."}]
        raise
    session.plan_output = out[-6000:]
    session.status = SessionStatus.planned
    attention_mod.refresh(session)
    last = [l for l in out.splitlines() if l.startswith("Plan:") or "No changes" in l]
    _emit("message", last[-1] if last else "Plan complete.", state="waiting")
    _emit("message", "Waiting for a human to approve before I apply anything.", state="waiting")
    return session


def approve(session: Session, decided_by: str) -> Session:
    from .pipeline import _current

    _current.set(session)
    if session.status != SessionStatus.planned:
        raise OperatorError("Only a planned stack can be approved")
    session.approved_by = decided_by
    session.status = SessionStatus.approved
    _emit("message", f"Approved by {decided_by}. Ready to apply.", state="waiting")
    return session


def apply(session: Session, root: Path) -> Session:
    from .pipeline import _current

    _current.set(session)
    if session.status != SessionStatus.approved or not session.approved_by:
        raise OperatorError("Apply requires an approved plan")
    ws = root / session.id
    if not (ws / "tfplan").exists():
        raise OperatorError("Saved plan missing; run plan again")
    session.status = SessionStatus.applying
    _emit("inbound", f"Applying plan approved by {session.approved_by}.", state="working")
    try:
        _emit("tool_call", "terraform apply tfplan")
        code, out = _run(["terraform", "apply", "-input=false", "-no-color", "tfplan"], ws, 3600)
    except FileNotFoundError:
        session.status = SessionStatus.failed
        raise OperatorError("terraform is not installed on the machine running the agent")
    session.apply_output = out[-6000:]
    if code != 0:
        session.status = SessionStatus.failed
        session.error = "terraform apply failed"
        _emit("error", out[-500:], state="error")
    else:
        session.status = SessionStatus.applied
        _emit("done", "Infrastructure applied.", state="idle")
        try:
            from . import stacks

            stacks.register(root, session)  # from now on the observability team watches it for drift
        except Exception:
            pass
    return session
