"""Tools the support agent can call. Built per request so they act for the signed-in user."""

from datetime import datetime, timezone
from typing import Dict

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class OrderArgs(BaseModel):
    order_id: str = Field(..., description="The order number, digits only or as the customer wrote it")


class TicketArgs(BaseModel):
    subject: str = Field(..., description="One-line summary of the problem")
    details: str = Field("", description="What the customer said, and what has been tried")
    priority: str = Field("normal", description="low, normal or high")


class NoArgs(BaseModel):
    pass


def build_tools(store, user) -> Dict[str, StructuredTool]:
    async def lookup_order_status(order_id: str) -> str:
        oid = "".join(ch for ch in order_id if ch.isalnum())
        rows = await store.select("orders", {"id": oid}, order=None, limit=1, token=user.token)
        if not rows:
            return f"No order found with number {order_id}. Ask the customer to double check it."
        o = rows[0]
        return f"Order {o['id']}: status {o['status']}, ETA {o.get('eta') or 'unknown'}, items {o.get('items')}."

    async def create_support_ticket(subject: str, details: str = "", priority: str = "normal") -> str:
        t = await store.insert("tickets", {
            "user_id": user.id, "subject": subject[:160], "details": details[:2000],
            "priority": priority if priority in ("low", "normal", "high") else "normal", "status": "open",
        }, token=user.token)
        return f"Ticket {str(t['id'])[:8]} created with priority {t['priority']}. A human agent will follow up."

    async def current_time() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    mk = StructuredTool.from_function
    return {
        t.name: t for t in [
            mk(coroutine=lookup_order_status, name="lookup_order_status", args_schema=OrderArgs,
               description="Look up the status, ETA and items of an order by its number. Always use this before stating order details."),
            mk(coroutine=create_support_ticket, name="create_support_ticket", args_schema=TicketArgs,
               description="Open a ticket for a human agent when the problem cannot be solved here."),
            mk(coroutine=current_time, name="current_time", args_schema=NoArgs, description="Current UTC time."),
        ]
    }
