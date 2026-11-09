from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventKind(str, Enum):
    status = "status"          # member changed state (idle/working/waiting/error)
    message = "message"        # something the member says / writes
    thinking = "thinking"      # LLM call started
    tool_call = "tool_call"    # member invoked a tool
    tool_result = "tool_result"
    handoff = "handoff"        # member passes work to another member
    inbound = "inbound"        # a human (or another service) spoke to the member
    error = "error"
    done = "done"


class MemberState(str, Enum):
    idle = "idle"
    working = "working"
    waiting = "waiting"  # blocked on a human / external system
    error = "error"


class AgentEvent(BaseModel):
    """One line in a colleague's message box."""

    id: int = 0
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    team: str
    member: str
    kind: EventKind = EventKind.message
    text: str = ""
    state: Optional[MemberState] = None
    to_team: Optional[str] = None
    to_member: Optional[str] = None
    simulated: bool = False
    meta: Dict[str, Any] = Field(default_factory=dict)


class Member(BaseModel):
    id: str
    name: str
    role: str
    # What this colleague is in the code, shown on hover.
    component: str = ""


class Team(BaseModel):
    id: str
    name: str
    tagline: str
    built: bool = True  # False = agent not implemented yet; cabin shows as onboarding
    chat_enabled: bool = False
    wide: bool = False  # spans the full floor width (big teams)
    accent: str = "#4f7cff"
    members: List[Member]


class MemberSnapshot(BaseModel):
    team: str
    member: str
    state: MemberState = MemberState.idle
    last_event_id: int = 0


class Roster(BaseModel):
    teams: List[Team]
    members: List[MemberSnapshot]
