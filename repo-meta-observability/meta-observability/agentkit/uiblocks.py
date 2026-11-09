"""
Generative UI. The model answers in plain sentences and may append `<ui>{...}</ui>` describing blocks to render under
the message (cards, steps, tables, charts, stats, code, checklists) plus a mood and quick replies. The frontend maps
each block type to an animated component, so every answer can look different. Invalid blocks are dropped, never shown.
"""

import json
import re
from typing import Annotated, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator

Tone = Literal["info", "success", "warning", "danger", "neutral"]
Mood = Literal["calm", "upbeat", "urgent", "celebrate", "thinking"]


def _clip(v: str, n: int) -> str:
    return v if len(v) <= n else v[: n - 1] + "…"


class Action(BaseModel):
    label: str
    prompt: str = ""

    @field_validator("label")
    @classmethod
    def _l(cls, v):
        return _clip(v, 40)


class CardBlock(BaseModel):
    type: Literal["card"]
    title: str
    body: str = ""
    icon: str = "✨"
    tone: Tone = "info"
    actions: List[Action] = Field(default_factory=list, max_length=3)


class StepItem(BaseModel):
    label: str
    detail: str = ""
    status: Literal["done", "active", "todo"] = "todo"


class StepsBlock(BaseModel):
    type: Literal["steps"]
    title: str = ""
    steps: List[StepItem] = Field(max_length=10)


class TableBlock(BaseModel):
    type: Literal["table"]
    title: str = ""
    columns: List[str] = Field(max_length=8)
    rows: List[List[str]] = Field(max_length=20)


class Series(BaseModel):
    name: str
    values: List[float] = Field(max_length=24)


class ChartBlock(BaseModel):
    type: Literal["chart"]
    title: str = ""
    kind: Literal["bar", "line", "donut"] = "bar"
    labels: List[str] = Field(max_length=24)
    series: List[Series] = Field(max_length=4)


class Stat(BaseModel):
    label: str
    value: str
    delta: Optional[str] = None
    tone: Tone = "neutral"


class StatsBlock(BaseModel):
    type: Literal["stats"]
    items: List[Stat] = Field(max_length=6)


class CodeBlock(BaseModel):
    type: Literal["code"]
    language: str = ""
    filename: str = ""
    code: str


class CheckItem(BaseModel):
    text: str
    done: bool = False


class ChecklistBlock(BaseModel):
    type: Literal["checklist"]
    title: str = ""
    items: List[CheckItem] = Field(max_length=12)


Block = Annotated[
    Union[CardBlock, StepsBlock, TableBlock, ChartBlock, StatsBlock, CodeBlock, ChecklistBlock],
    Field(discriminator="type"),
]
_block_adapter = TypeAdapter(Block)


class UiPayload(BaseModel):
    mood: Mood = "calm"
    blocks: List[Block] = Field(default_factory=list)
    quick_replies: List[str] = Field(default_factory=list)

    @field_validator("quick_replies")
    @classmethod
    def _q(cls, v):
        return [_clip(x, 48) for x in v[:4]]


def parse_ui(raw: str) -> Optional[UiPayload]:
    """Lenient: strips code fences, keeps every valid block, drops the rest."""
    raw = re.sub(r"^\s*```(?:json)?|```\s*$", "", raw.strip(), flags=re.I | re.M).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    blocks = []
    for b in (data.get("blocks") or [])[:6]:
        try:
            blocks.append(_block_adapter.validate_python(b))
        except ValidationError:
            continue
    try:
        mood = data.get("mood", "calm")
        return UiPayload(mood=mood if mood in Mood.__args__ else "calm", blocks=blocks, quick_replies=[str(x) for x in (data.get("quick_replies") or [])])
    except ValidationError:
        return UiPayload(blocks=blocks)


UI_PROMPT = """
After your plain-text reply you may append ONE <ui>...</ui> element containing JSON that tells the app how to present
richer content. Use it when it genuinely helps (comparisons, steps, numbers, code, status). Vary the presentation to fit
each answer; do not repeat the same layout every time. Never put the same text in both the reply and the blocks.
JSON shape: {"mood": "calm|upbeat|urgent|celebrate|thinking", "blocks": [...], "quick_replies": ["...", "..."]}
Block types (use "type"):
 card      {title, body, icon (one emoji), tone: info|success|warning|danger|neutral, actions: [{label, prompt}]}
 steps     {title, steps: [{label, detail, status: done|active|todo}]}
 table     {title, columns: [..], rows: [[..]]}
 chart     {title, kind: bar|line|donut, labels: [..], series: [{name, values: [numbers]}]}
 stats     {items: [{label, value, delta, tone}]}
 code      {language, filename, code}
 checklist {title, items: [{text, done}]}
Keep it to at most 4 blocks and 3 quick replies. Skip <ui> entirely for simple conversational answers.
""".strip()


class UiSplitter:
    """Streams visible text while holding back anything that might be the start of a <ui> element."""

    OPEN, CLOSE = "<ui>", "</ui>"

    def __init__(self) -> None:
        self.buf = ""
        self.mode = "text"
        self.ui: List[str] = []

    def feed(self, s: str) -> str:
        self.buf += s
        out = ""
        while True:
            if self.mode == "text":
                i = self.buf.find(self.OPEN)
                if i >= 0:
                    out += self.buf[:i]
                    self.buf = self.buf[i + len(self.OPEN):]
                    self.mode = "ui"
                    continue
                hold = 0
                for k in range(min(len(self.OPEN) - 1, len(self.buf)), 0, -1):
                    if self.buf.endswith(self.OPEN[:k]):
                        hold = k
                        break
                out += self.buf[: len(self.buf) - hold]
                self.buf = self.buf[len(self.buf) - hold:]
                return out
            j = self.buf.find(self.CLOSE)
            if j >= 0:
                self.ui.append(self.buf[:j])
                self.buf = self.buf[j + len(self.CLOSE):]
                self.mode = "text"
                continue
            return out

    def finish(self) -> Tuple[str, Optional[str]]:
        """(remaining visible text, raw ui json or None)"""
        tail = self.buf if self.mode == "text" else ""
        if self.mode == "ui" and self.buf.strip():
            self.ui.append(self.buf)  # unterminated; parse_ui decides if it is usable
        self.buf = ""
        return tail, (self.ui[-1] if self.ui else None)
