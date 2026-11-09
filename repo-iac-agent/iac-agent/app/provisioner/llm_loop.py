"""
One colleague's turn: call the LLM with tools until it submits a result that
validates against a Pydantic model. The submit step is itself a tool call
whose arguments are the model's schema, so output is always structured and
validation errors are fed back for the model to fix.
"""

import json
from typing import Callable, List, Sequence, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

Emit = Callable[..., None]


class StageFailed(RuntimeError):
    pass


def _short(value, limit: int = 220) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def run_stage(
    llm,
    *,
    system: str,
    user: str,
    tools: Sequence[BaseTool],
    submit: Type[T],
    member: str,
    emit: Emit,
    max_steps: int = 14,
    images: Sequence = (),
) -> T:
    by_name = {t.name: t for t in tools}
    bound = llm.bind_tools([*tools, submit])
    content = user if not images else [{"type": "text", "text": user}, *({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}} for mime, b64 in images)]
    messages: List = [SystemMessage(content=system), HumanMessage(content=content)]
    nudged = False

    for _ in range(max_steps):
        emit(member, "thinking", "Thinking...", state="working")
        ai = bound.invoke(messages)
        messages.append(ai)

        if not ai.tool_calls:
            if ai.content:
                emit(member, "message", str(ai.content)[:600])
            if nudged:
                raise StageFailed(f"{member}: model answered without submitting {submit.__name__}")
            nudged = True
            messages.append(HumanMessage(content=f"Finish by calling the {submit.__name__} tool with your result."))
            continue

        for call in ai.tool_calls:
            name, args, call_id = call["name"], call["args"], call["id"]
            if name == submit.__name__:
                try:
                    return submit.model_validate(args)
                except ValidationError as exc:
                    emit(member, "error", f"My {submit.__name__} was invalid, fixing: {_short(str(exc), 300)}")
                    messages.append(ToolMessage(content=f"Validation failed, resubmit: {exc}", tool_call_id=call_id))
                    continue
            tool = by_name.get(name)
            if tool is None:
                messages.append(ToolMessage(content=f"ERROR: unknown tool {name}", tool_call_id=call_id))
                continue
            emit(member, "tool_call", f"{name}({_short(args, 160)})")
            try:
                result = tool.invoke(args)
            except Exception as exc:
                result = f"ERROR: {type(exc).__name__}: {exc}"
            emit(member, "tool_result", _short(result, 260))
            messages.append(ToolMessage(content=str(result), tool_call_id=call_id))

    raise StageFailed(f"{member}: no valid {submit.__name__} after {max_steps} steps")
