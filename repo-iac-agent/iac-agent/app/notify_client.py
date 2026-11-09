from typing import Any, Dict, List, Optional

import httpx

from .config import settings
from .secrets import secrets


def _headers() -> Dict[str, str]:
    if secrets.agent_api_token:
        return {"X-Agent-Token": secrets.agent_api_token}
    return {}


def submit_finding(payload: Dict[str, Any], *, client: Optional[httpx.Client] = None) -> Dict[str, Any]:
    owns_client = client is None
    client = client or httpx.Client(base_url=settings.backend_url, timeout=15.0)
    try:
        response = client.post("/ops/findings", json=payload, headers=_headers())
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            client.close()


def get_findings_awaiting_apply(*, client: Optional[httpx.Client] = None) -> List[Dict[str, Any]]:
    owns_client = client is None
    client = client or httpx.Client(base_url=settings.backend_url, timeout=15.0)
    try:
        response = client.get("/ops/findings/awaiting-apply", headers=_headers())
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            client.close()


def report_apply_result(
    finding_id: str, *, success: bool, detail: str, client: Optional[httpx.Client] = None
) -> Dict[str, Any]:
    owns_client = client is None
    client = client or httpx.Client(base_url=settings.backend_url, timeout=15.0)
    try:
        response = client.post(
            f"/ops/findings/{finding_id}/apply-result",
            json={"success": success, "detail": detail},
            headers=_headers(),
        )
        response.raise_for_status()
        return response.json()
    finally:
        if owns_client:
            client.close()
