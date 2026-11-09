"""
Things only the person can fix. Computed from the session state, shown in the Infrastructure UI as "Needs your attention" and
spoken in the Agent Office by the colleague it concerns, so nothing is hidden in one place.
"""

import os
import shutil
from typing import Any, Dict, List

from .. import office_client
from .schemas import SessionStatus


def compute(session) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    req, arch, rev = session.requirements, session.architecture, session.review
    if session.status == SessionStatus.needs_answers and req and req.questions:
        for i, q in enumerate(req.questions):
            items.append({"id": f"q{i}", "kind": "question", "severity": "info", "member": "requirements", "title": "Rhea needs an answer", "detail": q, "how_to_fix": "Answer in the chat. Pick an option or write your own."})
    if rev and not rev.approved_for_plan:
        for i, f in enumerate(x for x in rev.findings if x.severity == "blocker"):
            items.append({"id": f"b{i}", "kind": "decision", "severity": "blocker", "member": "reviewer", "title": "Rex found a blocker", "detail": f"{f.resource}: {f.message}",
                          "how_to_fix": f.suggestion or "Tell the team how to change the design, or accept the risk explicitly in the chat."})
    if arch and session.status in (SessionStatus.ready_for_plan, SessionStatus.planned, SessionStatus.approved, SessionStatus.applying):
        missing = [v for v in arch.provider.auth_env_vars if not os.environ.get(v)]
        if missing:
            items.append({"id": "creds", "kind": "setup", "severity": "warning", "member": "operator", "title": f"Credentials for {arch.provider.cloud} are not set",
                          "detail": f"The Infrastructure agent cannot reach {arch.provider.cloud} without {', '.join(missing)}.",
                          "how_to_fix": f"Set {', '.join(missing)} in the environment of the Infrastructure agent (never paste it into a chat), then restart the agent."})
        if shutil.which("terraform") is None:
            items.append({"id": "terraform", "kind": "setup", "severity": "warning", "member": "operator", "title": "Terraform is not installed",
                          "detail": "The design and files are ready, but plan and apply need the terraform program on the machine running the agent.",
                          "how_to_fix": "Install Terraform 1.5 or newer and add it to PATH, or download the files and run them yourself."})
    if session.status == SessionStatus.failed and session.error:
        items.append({"id": "failed", "kind": "error", "severity": "blocker", "member": "operator" if session.plan_output or session.apply_output else "requirements",
                      "title": "The last step failed", "detail": session.error[:300], "how_to_fix": "Read the error, adjust your request or environment, then try again in the chat."})
    return items


def refresh(session) -> None:
    """Recomputes the list and tells the Agent Office about anything new."""
    new = compute(session)
    known = {a["id"] for a in session.attention}
    session.attention = new
    for a in new:
        if a["id"] not in known and a["kind"] != "question":  # questions are already spoken as Rhea's reply
            office_client.emit(a["member"], "message", f"Needs you: {a['title']}. {a['how_to_fix']}"[:380], state="waiting")
