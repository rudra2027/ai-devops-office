"""
Parses the output of `terraform show -json <planfile>` into ResourceChange
objects. Deliberately separate from the subprocess calls that produce that
JSON (see terraform_cli.py) — this module takes a plain dict and returns
plain objects, so it's fully testable without a terraform binary or AWS
credentials, using a saved/fixture plan document.

Real terraform show -json output shape (the parts we use):
{
  "resource_drift": [ {address, type, change: {actions, before, after}}, ... ],
  "resource_changes": [ {address, type, change: {actions, before, after}}, ... ]
}
`resource_drift` = detected during refresh: infra changed outside Terraform.
`resource_changes` = what apply would do to reconcile state with config —
may overlap with drift-driven changes or be intentional config changes.
"""

from typing import Any, Dict, List

from .models import ResourceChange

_NOOP_ACTIONS = ({"no-op"}, set())


def _diff_attributes(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Top-level attribute diff between before/after — good enough for a
    human-readable summary; doesn't recurse into nested blocks."""
    before = before or {}
    after = after or {}
    changed = {}
    for key in set(before.keys()) | set(after.keys()):
        if before.get(key) != after.get(key):
            changed[key] = {"before": before.get(key), "after": after.get(key)}
    return changed


def _parse_entries(entries: List[Dict[str, Any]], source: str) -> List[ResourceChange]:
    results = []
    for entry in entries:
        change = entry.get("change", {})
        actions = change.get("actions", [])
        if set(actions) in _NOOP_ACTIONS:
            continue
        results.append(
            ResourceChange(
                address=entry["address"],
                resource_type=entry["type"],
                actions=actions,
                source=source,
                changed_attributes=_diff_attributes(
                    change.get("before") or {}, change.get("after") or {}
                ),
            )
        )
    return results


def parse_changes(plan_json: Dict[str, Any]) -> List[ResourceChange]:
    """Main entry point. Returns drift-sourced changes first, then
    planned-but-not-drift changes, deduplicated by address (a resource that
    shows up in both is drift, not just a pending config change)."""
    drift = _parse_entries(plan_json.get("resource_drift", []), source="drift")
    drift_addresses = {c.address for c in drift}

    planned = [
        c
        for c in _parse_entries(plan_json.get("resource_changes", []), source="planned")
        if c.address not in drift_addresses
    ]

    return drift + planned
