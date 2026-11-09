from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


class ResourceChange(BaseModel):
    """One resource's change, extracted from `terraform show -json`'s
    output. Covers both `resource_drift` (detected during refresh — infra
    changed outside Terraform) and `resource_changes` (what apply would do
    to reconcile state with config) — `source` tells you which."""

    address: str
    resource_type: str
    actions: List[str]
    source: Literal["drift", "planned"]
    changed_attributes: Dict[str, Dict[str, Any]]  # attr -> {"before": ..., "after": ...}

    @property
    def is_destroy(self) -> bool:
        return "delete" in self.actions

    @property
    def is_tags_only(self) -> bool:
        keys = set(self.changed_attributes.keys())
        return bool(keys) and keys.issubset({"tags", "tags_all"})


class Classification(BaseModel):
    risk_score: int
    auto_apply: bool
    summary: str
    matched_rule: str
