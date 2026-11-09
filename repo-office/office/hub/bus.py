import asyncio
from collections import deque
from typing import Deque, Dict, List, Set, Tuple

from .models import AgentEvent, EventKind, MemberSnapshot, MemberState
from .roster import MEMBER_IDS

MAX_EVENTS = 2000


class EventBus:
    """In-memory ring buffer plus SSE fan-out. Single process only; swap for
    Redis pub/sub if the hub is ever scaled out."""

    def __init__(self) -> None:
        self._events: Deque[AgentEvent] = deque(maxlen=MAX_EVENTS)
        self._next_id = 1
        self._states: Dict[Tuple[str, str], MemberState] = {k: MemberState.idle for k in MEMBER_IDS}
        self._subscribers: Set[asyncio.Queue] = set()

    def publish(self, event: AgentEvent) -> AgentEvent:
        event.id = self._next_id
        self._next_id += 1
        if event.state is not None:
            self._states[(event.team, event.member)] = event.state
        elif event.kind == EventKind.error:
            self._states[(event.team, event.member)] = MemberState.error
        elif event.kind == EventKind.done:
            self._states[(event.team, event.member)] = MemberState.idle
        self._events.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                self._subscribers.discard(q)  # slow client; it will reconnect and replay
        return event

    def since(self, last_id: int) -> List[AgentEvent]:
        return [e for e in self._events if e.id > last_id]

    def snapshots(self) -> List[MemberSnapshot]:
        return [
            MemberSnapshot(team=t, member=m, state=s) for (t, m), s in sorted(self._states.items())
        ]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)


bus = EventBus()
