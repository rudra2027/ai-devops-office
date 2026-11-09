"""IaC team's window into the Agent Office. Thin wrapper over the shared kit so settings come from one place."""

from typing import Optional

from agentkit import office as _office

TEAM = "iac"


def emit(member: str, kind: str, text: str, *, state: Optional[str] = None, to_member: Optional[str] = None, team: str = TEAM) -> None:
    _office.emit(team, member, kind, text, state=state, to_member=to_member)
