"""
Thin client for the public Terraform Registry. This is how the agent learns
any cloud's vocabulary at runtime instead of hard-coding AWS/Azure/GCP: it
finds the provider, lists its resource types, and reads the docs of the ones
it intends to use.
"""

from functools import lru_cache
from typing import Any, Dict, List, Optional

import httpx

BASE = "https://registry.terraform.io"
_TIMEOUT = 20.0
_DOC_LIMIT = 9000  # chars of a resource doc handed to the LLM


class RegistryError(RuntimeError):
    pass


def _get(path: str, **params: Any) -> Dict[str, Any]:
    try:
        r = httpx.get(f"{BASE}{path}", params=params or None, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise RegistryError(f"Registry unreachable: {exc}") from exc
    if r.status_code == 404:
        raise RegistryError(f"Not found in registry: {path}")
    if r.status_code >= 400:
        raise RegistryError(f"Registry returned {r.status_code} for {path}")
    return r.json()


def search_providers(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    data = _get("/v1/providers", q=query, limit=limit)
    out = []
    for p in data.get("providers", []):
        out.append(
            {
                "source": f"{p['namespace']}/{p['name']}",
                "tier": p.get("tier"),
                "latest_version": p.get("version"),
                "downloads": p.get("downloads"),
                "description": (p.get("description") or "")[:160],
            }
        )
    # Official/partner providers with many downloads first; the LLM still decides.
    tier_rank = {"official": 0, "partner": 1}
    out.sort(key=lambda p: (tier_rank.get(p["tier"], 2), -(p["downloads"] or 0)))
    return out


@lru_cache(maxsize=64)
def _provider(source: str) -> Dict[str, Any]:
    if source.count("/") != 1:
        raise RegistryError(f"Provider source must look like 'namespace/name', got {source!r}")
    return _get(f"/v1/providers/{source}")


def provider_info(source: str) -> Dict[str, Any]:
    p = _provider(source)
    return {"source": source, "version": p["version"], "description": p.get("description", "")}


def list_resources(source: str, keyword: str = "", category: str = "resources", limit: int = 40) -> List[str]:
    """Resource (or data-source) type names whose doc slug contains keyword."""
    p = _provider(source)
    prefix = p["name"]
    kw = keyword.lower().strip()
    names = [
        f"{prefix}_{d['slug']}"
        for d in p.get("docs", [])
        if d["category"] == category and (not kw or kw in d["slug"].lower() or kw in d["title"].lower())
    ]
    return names[:limit]


def _find_doc_id(source: str, resource_type: str, category: str) -> Optional[str]:
    p = _provider(source)
    slug = resource_type[len(p["name"]) + 1:] if resource_type.startswith(p["name"] + "_") else resource_type
    for d in p.get("docs", []):
        if d["category"] == category and d["slug"] == slug:
            return d["id"]
    return None


def resource_doc(source: str, resource_type: str, category: str = "resources") -> str:
    doc_id = _find_doc_id(source, resource_type, category)
    if doc_id is None:
        raise RegistryError(
            f"No {category} doc named {resource_type!r} in {source}. Use list_provider_resources to find the exact name."
        )
    content = _get(f"/v2/provider-docs/{doc_id}")["data"]["attributes"]["content"]
    if len(content) > _DOC_LIMIT:
        content = content[:_DOC_LIMIT] + "\n...[truncated]"
    return content
