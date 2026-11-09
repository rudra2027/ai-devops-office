"""
Run lifecycle:  reviewing -> awaiting_approval -> (approve) running -> succeeded | failed      or  rejected | error

The reviewer's summary is what a human approves. Execution then runs each stage in a worker thread, updating the run
as it goes so the UI can poll. Failures get an LLM diagnosis ("self-heal" suggestion) and an optional Telegram alert.
"""

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage

from agentkit import office as office_mod
from agentkit.llm import get_chat_model
from agentkit.tracing import run_config

from . import stages
from .review import review_diff

MAX_AUTO_HEALS = 2  # automatic retries for transient failures; beyond that a human decides
office = office_mod.Team("cicd")
TABLE = "pipeline_runs"

_TRANSIENT = re.compile(r"timed out|read ?timeout|connect ?timeout|etimedout|connection (reset|refused|aborted)|econn(reset|refused|aborted)|temporar(il)?y unavailable|rate limit|too many requests|"
                        r"50[234]|network is unreachable|name resolution|service unavailable|could not resolve host|tls handshake", re.I)
_TEST_FAILED = re.compile(r"AssertionError|FAILED|failed.*tests?|\d+ failed", re.I)


def classify_failure(stage_id: str, log: str) -> str:
    """transient (worth retrying), security, code, config or unknown. Heuristic first; the LLM may refine it."""
    low = log.lower()
    if stage_id == "scan" and ("[secret]" in low or "secret scan on added lines: failed" in low):
        return "security"
    if _TRANSIENT.search(log) and not _TEST_FAILED.search(log):
        return "transient"  # a network signature, and no failing assertion that would explain the failure on its own
    if stage_id in ("tests",):
        return "code"
    if "not found" in low or "no such file" in low or "permission denied" in low or "not installed" in low:
        return "config"
    return "unknown"
_runs: Dict[str, Dict[str, Any]] = {}
_exec_slots = asyncio.Semaphore(2)

STAGE_DEFS = [("tests", "Tests", "tester"), ("scan", "Security scan", "scanner"), ("build", "Build image", "builder"), ("deploy", "Roll out", "release")]


def new_run(user_id: str, title: str, diff: str, source: str, model: str, repo: Optional[str] = None, base: str = "", head: str = "", test_command: str = "") -> Dict[str, Any]:
    rid = uuid.uuid4().hex[:10]
    run = {
        "id": rid, "user_id": user_id, "title": title[:80] or "Untitled change", "source": source, "repo": repo, "base": base, "head": head,
        "diff": diff, "model": model, "status": "reviewing", "created_at": time.time(), "updated_at": time.time(), "test_command": test_command,
        "review": None, "stages": [{"id": i, "label": l, "member": m, "status": "pending", "log": "", "duration_ms": None} for i, l, m in STAGE_DEFS],
        "approved_by": None, "rejected_by": None, "heal": None, "notified": None, "error": None, "events": [],
        "heal_attempts": 0, "attention": [], "heal_log": [],
    }
    _runs[rid] = run
    return run


def public(run: Dict[str, Any]) -> Dict[str, Any]:
    d = {k: v for k, v in run.items() if k not in ("diff",)}
    d["diff_lines"] = run["diff"].count("\n") + 1
    d["diff_preview"] = run["diff"][:6000]
    return d


def _ev(run, member: str, kind: str, text: str, **kw) -> None:
    run["events"].append({"t": time.time(), "member": member, "kind": kind, "text": text[:400]})
    run["events"] = run["events"][-80:]
    run["updated_at"] = time.time()
    office(member, kind, text, **kw)


async def start_review(run: Dict[str, Any], persist) -> None:
    run["status"] = "reviewing"
    _ev(run, "reviewer", "inbound", f"New change: {run['title']} ({run['diff'].count(chr(10)) + 1} diff lines)", state="working")
    _ev(run, "reviewer", "thinking", "Reading the diff...")
    try:
        r = await review_diff(run["diff"], run["model"], context=f"Change title: {run['title']}")
    except Exception as exc:
        run["status"], run["error"] = "error", f"{type(exc).__name__}: {exc}"[:300]
        _ev(run, "reviewer", "error", run["error"])
        await persist(run)
        return
    run["review"] = r.model_dump()
    run["status"] = "awaiting_approval"
    _ev(run, "reviewer", "message", f"{r.title}. Risk {r.risk}, {len(r.findings)} finding(s).", state="waiting")
    if r.findings:
        worst = sorted(r.findings, key=lambda f: {"blocker": 0, "warning": 1, "info": 2}[f.severity])[0]
        _ev(run, "reviewer", "message", f"[{worst.severity}] {worst.file}: {worst.issue}"[:300])
    await persist(run)


def hard_blockers(run) -> list:
    return [f for f in (run.get("review") or {}).get("findings", []) if f["severity"] == "blocker" and "added to source" in f["issue"]]


async def execute(run: Dict[str, Any], persist, roots) -> None:
    async with _exec_slots:
        run["status"] = "running"
        repo: Optional[Path] = None
        if run["repo"]:
            try:
                repo = stages.safe_repo(run["repo"], roots)
            except Exception as exc:
                run["status"], run["error"] = "error", str(exc)
                await persist(run)
                return
        tag = f"cicd-{run['id']}"
        runners = {
            "tests": lambda: stages.run_tests(repo, run.get("test_command") or None),
            "scan": lambda: stages.run_scan(repo, run["diff"]),
            "build": lambda: stages.run_build(repo, tag),
            "deploy": lambda: stages.run_deploy(tag),
        }
        failed_stage = None
        prev = "reviewer"
        for st in run["stages"]:
            st.update(status="running", log="", duration_ms=None)
            _ev(run, prev, "handoff", f"Over to the {st['label'].lower()} stage.", state="idle", to_member=st["member"])
            _ev(run, st["member"], "tool_call", f"{st['label']}...", state="working")
            await persist(run)
            t0 = time.perf_counter()
            try:
                status, log = await asyncio.to_thread(runners[st["id"]])
            except Exception as exc:
                status, log = "failed", f"{type(exc).__name__}: {exc}"
            st.update(status=status, log=log, duration_ms=int((time.perf_counter() - t0) * 1000))
            _ev(run, st["member"], "tool_result" if status != "failed" else "error", f"{st['label']}: {status}", state="idle")
            prev = st["member"]
            if status == "failed":
                failed_stage = st
                break
        if failed_stage:
            run["status"] = "failed"
            for st in run["stages"]:
                if st["status"] == "pending":
                    st["status"] = "skipped"
                    st["log"] = "Not run because an earlier stage failed."
            await _heal(run, failed_stage)
            _attention(run, failed_stage)
            await _notify(run, f"Pipeline failed at {failed_stage['label']}: {run['title']}")
        else:
            run["status"] = "succeeded"
            run["attention"] = [a for a in run["attention"] if a.get("persist")]
            _optional_notes(run)
            _ev(run, "release", "done", "Pipeline finished.", state="idle")
        await persist(run)


async def _heal(run: Dict[str, Any], st: Dict[str, Any]) -> None:
    _ev(run, "oncall", "tool_call", f"Diagnosing the {st['label'].lower()} failure...", state="working")
    try:
        llm = get_chat_model(run["model"], temperature=0, agent="cicd", fallback=True)
        msg = [SystemMessage(content="You are a CI engineer. A pipeline stage failed. Diagnose the most likely cause from the log and the change summary. "
                                     "Reply with JSON only: {\"diagnosis\": str, \"suggested_fix\": str, \"confidence\": \"low|medium|high\", \"kind\": \"transient|code|config|security\"}. kind=transient only when the failure is a flaky network/timeout/rate-limit that a plain retry may fix. The fix is a suggestion for a human; never claim it was applied."),
               HumanMessage(content=f"Change: {run['title']}\nStage: {st['label']}\nLog (tail):\n{st['log'][-3500:]}\n\nDiff (head):\n{run['diff'][:3000]}")]
        out = await llm.ainvoke(msg, config=run_config("cicd", stage=st["id"]))
        m = re.search(r"\{.*\}", str(out.content), re.S)
        run["heal"] = {"stage": st["label"], **json.loads(m.group(0))} if m else None
        if run["heal"] is not None:
            heuristic = classify_failure(st["id"], st["log"])
            llm_kind = run["heal"].get("kind")
            # Clear signatures in the log (a leaked secret, a network timeout) outrank the model; otherwise the model's reading stands.
            run["heal"]["kind"] = heuristic if heuristic in ("security", "transient") else (llm_kind if llm_kind in ("transient", "code", "config", "security") else heuristic)
    except Exception as exc:
        run["heal"] = {"stage": st["label"], "diagnosis": f"Automatic diagnosis unavailable ({type(exc).__name__}).", "suggested_fix": "", "confidence": "low", "kind": classify_failure(st["id"], st["log"])}
    if run["heal"]:
        _ev(run, "oncall", "message", run["heal"].get("diagnosis", "")[:300], state="waiting")


def _attention(run: Dict[str, Any], st: Dict[str, Any]) -> None:
    """Things only a person can fix. Shown in the CI/CD UI and spoken in the Agent Office."""
    kind = (run.get("heal") or {}).get("kind", "unknown")
    items = []
    if kind == "security":
        items.append({"severity": "blocker", "title": "A credential is in the change", "detail": (run["heal"] or {}).get("diagnosis") or "The secret scan found a credential.",
                      "how_to_fix": "Remove it from the code, rotate the credential, then submit the change again.", "persist": True})
    elif kind == "transient":
        left = MAX_AUTO_HEALS - run["heal_attempts"]
        if left <= 0:
            items.append({"severity": "blocker", "title": f"{st['label']} keeps failing after {run['heal_attempts']} automatic retries",
                          "detail": (run.get("heal") or {}).get("diagnosis", ""), "how_to_fix": "Check the service the stage depends on, then press Re-run.", "persist": True})
    else:
        items.append({"severity": "blocker", "title": f"{st['label']} failed and needs a code or configuration fix",
                      "detail": (run.get("heal") or {}).get("diagnosis", ""), "how_to_fix": (run.get("heal") or {}).get("suggested_fix") or "Open the stage log, fix the cause, then press Re-run.", "persist": True})
    run["attention"] = items
    for a in items:
        _ev(run, "oncall", "message", f"Needs you: {a['title']}. {a['how_to_fix']}"[:380], state="waiting")


def _optional_notes(run: Dict[str, Any]) -> None:
    for st in run["stages"]:
        if st["status"] != "skipped":
            continue
        fixes = {"tests": "Add a test suite or give the run a test command.", "build": "Set CICD_ENABLE_DOCKER=true on a machine with Docker.", "deploy": "Configure a rollout target (ARGOCD_SERVER)."}
        run["attention"].append({"severity": "info", "title": f"{st['label']} was skipped", "detail": st["log"][:240], "how_to_fix": fixes.get(st["id"], ""), "persist": False})


def restart(run: Dict[str, Any], *, auto: bool, reason: str = "") -> None:
    """Resets the stages for another pass. `auto` marks a retry made by the platform, not a person."""
    for st in run["stages"]:
        st.update(status="pending", log="", duration_ms=None)
    run["heal"], run["notified"], run["status"], run["attention"] = None, None, "running", []
    if auto:
        run["heal_attempts"] = int(run.get("heal_attempts") or 0) + 1
        run["heal_log"].append({"t": time.time(), "action": "auto_rerun", "attempt": run["heal_attempts"], "reason": reason})
    _ev(run, "release" if auto else "reviewer", "message", f"{'Auto-heal' if auto else 'Re-run'}: running the stages again. {reason}"[:300], state="working")


async def _notify(run: Dict[str, Any], text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        run["notified"] = "disabled (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)"
        return
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text})
        run["notified"] = "sent" if r.status_code == 200 else f"failed ({r.status_code})"
    except httpx.HTTPError:
        run["notified"] = "failed (network)"
    _ev(run, "oncall", "message", f"Telegram alert: {run['notified']}")
