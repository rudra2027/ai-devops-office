"""
Fire-and-forget publisher for the Agent Office hub. Every action a component takes is posted as a line in that
colleague's message box. Never raises and never blocks: with OFFICE_URL unset or the hub down, events are dropped.
"""

import json
import queue
import threading
import urllib.request
from typing import Optional

from .settings import get_settings

_q: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
_started = False
_lock = threading.Lock()


def _worker() -> None:
    while True:
        payload = _q.get()
        try:
            req = urllib.request.Request(
                f"{get_settings().office_url.rstrip('/')}/events",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "X-Ingest-Token": get_settings().ingest_token},
            )
            urllib.request.urlopen(req, timeout=2).read()
        except Exception:
            pass


def emit(team: str, member: str, kind: str, text: str, *, state: Optional[str] = None,
         to_member: Optional[str] = None, to_team: Optional[str] = None) -> None:
    global _started
    if not get_settings().office_url:
        return
    with _lock:
        if not _started:
            threading.Thread(target=_worker, daemon=True).start()
            _started = True
    payload = {"team": team, "member": member, "kind": kind, "text": text[:2000]}
    if state:
        payload["state"] = state
    if to_member:
        payload["to_team"] = to_team or team
        payload["to_member"] = to_member
    try:
        _q.put_nowait(payload)
    except queue.Full:
        pass


class Team:
    """emit() bound to one team: `office = Team('support'); office('agent', 'message', 'hi')`."""

    def __init__(self, team: str) -> None:
        self.team = team

    def __call__(self, member: str, kind: str, text: str, *, state: Optional[str] = None,
                 to_member: Optional[str] = None, to_team: Optional[str] = None) -> None:
        emit(self.team, member, kind, text, state=state, to_member=to_member, to_team=to_team)
