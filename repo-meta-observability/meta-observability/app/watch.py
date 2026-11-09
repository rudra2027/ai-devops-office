"""
The observability team at work: three watchers that open incidents, act within strict limits, and say out loud (in the
dashboard and in the Agent Office) when a person has to step in.

  platform   service down, CPU / memory pressure, slow or failing endpoints, blocked event loops, LLM provider trouble
  delivery   CI/CD runs. Transient failures are re-run automatically (at most twice). Code, config and security failures
             are never "fixed" automatically: they become a "needs you" incident with the diagnosis and the fix
  drift      infrastructure the IaC agent applied. Differences from the code become incidents; putting things back is
             only ever done after an explicit admin click
"""

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx

from agentkit import office as office_mod
from agentkit.settings import get_settings

from .engine import Engine, MetricQuery

log = logging.getLogger("obs.watch")
CICD = "http://127.0.0.1:8300"
IAC = "http://127.0.0.1:8100"
MAX_AUTO_HEALS = 2
office = office_mod.Team("observability")


class Watch:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.resolved: List[Dict[str, Any]] = []
        self._strikes: Dict[str, int] = {}
        self.run_state: Dict[str, Dict[str, Any]] = {}
        self.drift_checked: Dict[str, float] = {}

    def _hdr(self) -> Dict[str, str]:
        return {"X-Ingest-Token": get_settings().ingest_token}

    # ------------------------------------------------------------------ incidents
    def open(self, key: str, severity: str, title: str, detail: str = "", how_to_fix: str = "", needs_user: bool = False,
             source: str = "platform", member: str = "alerts", via: Optional[str] = None) -> None:
        if key in self.incidents:
            self.incidents[key].update(detail=detail, severity=severity)
            return
        inc = {"id": uuid.uuid4().hex[:8], "key": key, "severity": severity, "title": title, "detail": detail[:400], "how_to_fix": how_to_fix,
               "needs_user": needs_user, "source": source, "opened_at": time.time(), "resolved_at": None}
        self.incidents[key] = inc
        if via:
            office(via, "message", f"Spotted: {title}", state="working")
            office(via, "handoff", "Passing this to Alec.", to_member=member, state="idle")
        text = (f"Needs you: {title}. {how_to_fix}" if needs_user else f"{severity.upper()}: {title}. {detail}")[:380]
        office(member, "message", text, state="waiting" if needs_user else "working")
        office("scribe", "message", f"Logged incident {inc['id']}: {title}"[:200], state="idle")

    def resolve(self, key: str, note: str = "") -> None:
        inc = self.incidents.pop(key, None)
        if not inc:
            return
        inc["resolved_at"] = time.time()
        self.resolved = ([inc] + self.resolved)[:40]
        office("alerts", "message", f"Resolved: {inc['title']}. {note}"[:300], state="idle")

    def _debounced(self, key: str, bad: bool, need: int = 2) -> bool:
        """True once a condition has held for `need` checks in a row; stops flapping alerts."""
        if not bad:
            self._strikes[key] = 0
            return False
        self._strikes[key] = self._strikes.get(key, 0) + 1
        return self._strikes[key] >= need

    def summary(self) -> Dict[str, Any]:
        opened = sorted(self.incidents.values(), key=lambda i: i["opened_at"], reverse=True)
        return {"open": opened, "needs_you": [i for i in opened if i["needs_user"]], "recent_resolved": self.resolved[:10]}

    # ------------------------------------------------------------------ platform
    async def platform_tick(self) -> None:
        snap = self.engine.snapshot()
        for sid, s in snap["services"].items():
            label = s.get("label") or sid
            down = s.get("up") is False
            if self._debounced(f"down:{sid}", down):
                self.open(f"down:{sid}", "critical", f"{label} is not answering its health check", "The health probe has failed repeatedly.",
                          f"Check the {sid} log in repo-office/logs and start it again (python repo-office/shared/run_all.py).", True, via="collector")
            elif not down:
                self.resolve(f"down:{sid}", "It answers again.")
            if s.get("up") is None or down:
                continue
            checks = [
                ("cpu", (s.get("cpu_percent") or 0) > 60, "warning", f"{label} is using a lot of CPU ({s.get('cpu_percent')}% of the machine)", "A busy loop or heavy request is likely. Look at the top routes."),
                ("mem", (s.get("memory_mb") or 0) > 1500, "warning", f"{label} memory is high ({s.get('memory_mb')} MB)", "Possible leak. Restart it and watch whether memory keeps climbing."),
                ("slow", (s.get("latency_p95_ms") or 0) > 3000, "warning", f"{label} is slow (p95 {s.get('latency_p95_ms')} ms)", "Check dependencies it waits on (models, database)."),
                ("err", (s.get("error_rate") or 0) > 0.05, "critical", f"{label} is failing {round((s.get('error_rate') or 0) * 100, 1)}% of requests", "See the failing routes in its logs."),
                ("lag", (s.get("loop_lag_ms") or 0) > 250, "warning", f"{label} event loop is blocked ({s.get('loop_lag_ms')} ms lag)", "Something synchronous is running on the async loop."),
            ]
            for tag, bad, sev, title, fix in checks:
                key = f"{tag}:{sid}"
                via = {"cpu": "capacity", "mem": "capacity", "slow": "latency", "err": "failures", "lag": "latency"}[tag]
                if self._debounced(key, bad, 2):
                    self.open(key, sev, title, fix, fix, False, via=via)
                elif not bad:
                    self.resolve(key)
        h = snap["host"]
        for tag, v, limit, label in (("hostcpu", h.get("cpu_percent"), 90, "Machine CPU"), ("hostmem", h.get("memory_percent"), 90, "Machine memory"), ("hostdisk", h.get("disk_percent"), 90, "Disk space")):
            key = f"{tag}"
            if self._debounced(key, (v or 0) > limit, 2):
                self.open(key, "critical", f"{label} is at {v}%", "The machine itself is under pressure.", "Free resources or move services to a bigger machine.", True, via="capacity")
            elif (v or 0) <= limit:
                self.resolve(key)
        try:
            n = (await self.engine.query(MetricQuery(metric="llm.requests", window="15m"))).get("value") or 0
            er = (await self.engine.query(MetricQuery(metric="llm.error_rate", window="15m"))).get("value") or 0
            if self._debounced("llm_errors", n >= 5 and er > 0.2, 1):
                self.open("llm_errors", "critical", f"{round(er * 100)}% of model calls are failing", "The provider or the key may be having trouble.",
                          "Check the OpenRouter key balance and status, then retry.", True, via="failures")
            elif not (n >= 5 and er > 0.2):
                self.resolve("llm_errors")
        except Exception:
            pass

    # ------------------------------------------------------------------ delivery (CI/CD) with guard-railed auto-heal
    async def delivery_tick(self, c: httpx.AsyncClient) -> None:
        try:
            runs = (await c.get(f"{CICD}/api/internal/runs", headers=self._hdr())).json()
        except Exception:
            self.engine.delivery_error = "CI/CD agent unreachable"
            return
        self.engine.delivery_error = None
        self.engine.cicd_runs = [{"id": r["id"], "title": r["title"], "status": r["status"], "created_at": r["created_at"], "heal_attempts": r.get("heal_attempts", 0),
                                  "stages": r.get("stages", []), "kind": (r.get("heal") or {}).get("kind")} for r in runs]
        now = time.time()
        for r in runs:
            st = self.run_state.setdefault(r["id"], {"reported": False, "healed": False})
            heal, attempts, key = r.get("heal") or {}, r.get("heal_attempts", 0), f"run:{r['id']}"
            if r["status"] == "failed" and heal:
                kind = heal.get("kind")
                if kind == "transient" and attempts < MAX_AUTO_HEALS:
                    if now - r["updated_at"] < 20 * (attempts + 1):
                        continue  # back off before retrying
                    office("failures", "message", f"'{r['title']}' failed for a transient reason: {heal.get('diagnosis', '')[:140]}", state="working")
                    try:
                        resp = await c.post(f"{CICD}/api/internal/runs/{r['id']}/auto-heal", headers=self._hdr())
                    except Exception:
                        continue
                    if resp.status_code == 200:
                        self.engine.heal_log.insert(0, {"t": now, "run_id": r["id"], "title": r["title"], "action": "auto_rerun", "attempt": resp.json()["attempt"],
                                                        "reason": heal.get("diagnosis", "")[:200], "kind": kind})
                        office("failures", "handoff", f"Retrying automatically (attempt {resp.json()['attempt']} of {MAX_AUTO_HEALS}).", to_member="alerts", state="idle")
                        office("alerts", "message", f"Auto-heal: re-running '{r['title']}'", state="working")
                elif not st["reported"]:
                    st["reported"] = True
                    why = "Automatic retries are used up." if kind == "transient" else {"security": "A credential was found.", "code": "The code or tests need a fix.", "config": "The environment needs a change."}.get(kind, "It needs a person.")
                    self.open(key, "critical" if kind == "security" else "warning", f"Pipeline '{r['title']}' failed: {why}", heal.get("diagnosis", ""),
                              heal.get("suggested_fix") or "Open the run in the CI/CD agent, fix the cause, then re-run.", True, source="delivery", via="failures")
                    self.engine.heal_log.insert(0, {"t": now, "run_id": r["id"], "title": r["title"], "action": "needs_human", "attempt": attempts, "reason": why, "kind": kind})
            elif r["status"] == "succeeded":
                if attempts > 0 and not st["healed"]:
                    st["healed"] = True
                    self.engine.heal_log.insert(0, {"t": now, "run_id": r["id"], "title": r["title"], "action": "healed", "attempt": attempts, "reason": "Passed after an automatic retry", "kind": "transient"})
                    office("alerts", "message", f"Healed: '{r['title']}' passed after {attempts} automatic retr{'y' if attempts == 1 else 'ies'}.", state="idle")
                self.resolve(key, "The pipeline passes now.")
        self.engine.heal_log = self.engine.heal_log[:100]

    # ------------------------------------------------------------------ infrastructure drift
    async def drift_tick(self, c: httpx.AsyncClient, force: bool = False) -> None:
        try:
            stacks = (await c.get(f"{IAC}/iac/internal/stacks", headers=self._hdr())).json()
        except Exception:
            self.engine.drift_state = {"stacks": self.engine.drift_state.get("stacks", []), "error": "Infrastructure agent unreachable", "checked_at": time.time()}
            return
        now = time.time()
        out = []
        for s in stacks:
            last = self.drift_checked.get(s["id"], 0)
            if force or now - last > 300:
                office("anomaly", "tool_call", f"Checking {s['title']} for drift", state="working")
                try:
                    resp = await c.post(f"{IAC}/iac/internal/stacks/{s['id']}/drift-check", headers=self._hdr(), timeout=900)
                    if resp.status_code == 200:
                        s = resp.json()
                        self.drift_checked[s["id"]] = now
                except Exception:
                    pass
            d = s.get("drift") or {"status": "unchecked", "findings": []}
            out.append({"id": s["id"], "title": s["title"], "cloud": s.get("cloud"), "region": s.get("region"), "resources": s.get("resources"), "applied_at": s.get("applied_at"),
                        "status": d["status"], "checked_at": d.get("checked_at"), "findings": d.get("findings", []), "error": d.get("error"), "how_to_fix": d.get("how_to_fix")})
            key_d, key_c = f"drift:{s['id']}", f"drift_unchecked:{s['id']}"
            if d["status"] == "drift":
                worst = max((f.get("risk_score", 0) for f in d["findings"]), default=0)
                self.open(key_d, "critical" if worst >= 70 else "warning", f"{s['title']} has drifted from its code ({len(d['findings'])} difference(s))",
                          "; ".join(f"{f['resource']}: {f['summary']}" for f in d["findings"][:3]), "Review the differences in the Drift tab and approve putting them back, or update the code.", True, source="drift", via="anomaly")
                self.resolve(key_c)
            elif d["status"] == "cannot_check":
                self.open(key_c, "warning", f"Cannot check {s['title']} for drift", d.get("error", ""), d.get("how_to_fix", ""), True, source="drift", via="anomaly")
                self.resolve(key_d)
            elif d["status"] == "in_sync":
                self.resolve(key_d, "It matches its code again.")
                self.resolve(key_c)
        self.engine.drift_state = {"stacks": out, "error": None, "checked_at": now}


async def run_watchers(w: Watch) -> None:
    async with httpx.AsyncClient(timeout=8) as c:
        i = 0
        while True:
            try:
                await w.platform_tick()
                await w.delivery_tick(c)
                if i % 4 == 0:  # drift every ~minute
                    await w.drift_tick(c)
            except Exception:
                log.exception("watch tick failed")
            i += 1
            await asyncio.sleep(15)
