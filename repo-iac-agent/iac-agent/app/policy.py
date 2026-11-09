"""
Classifies a ResourceChange into a risk score and an auto-apply decision.

This is a plain-Python rule engine, not real OPA/Rego. That's a deliberate
scope choice for this build, not a design endorsement — the actual OPA
binary isn't available in every environment this code needs to run in
during development, and the rules below are simple enough that a rule
engine adds ceremony without much safety benefit yet. If/when the ruleset
grows past what's comfortable to review as Python (many resource types,
org-specific exceptions, need for a policy audit trail separate from code
review), port these rules into real .rego files and swap this module for
an OPA client call — the ResourceChange -> Classification interface below
stays the same either way, so nothing upstream needs to change.

The one rule that is NOT overridable by anything below: config.py's
high_risk_threshold is a hard ceiling applied by the caller (drift_scan.py),
not here — see its docstring.
"""

from .config import settings
from .models import Classification, ResourceChange

# Resource types where ANY change always requires human approval, no matter
# how small — these are the "blast radius" categories from the build guide:
# IAM, network access control, and the cluster/data-plane control surface.
_ALWAYS_HIGH_RISK_TYPES = {
    "aws_iam_role",
    "aws_iam_role_policy",
    "aws_iam_role_policy_attachment",
    "aws_iam_policy",
    "aws_security_group",
    "aws_security_group_rule",
    "aws_vpc_security_group_ingress_rule",
    "aws_vpc_security_group_egress_rule",
    "aws_network_acl",
    "aws_network_acl_rule",
    "aws_eks_cluster",
    "aws_iam_openid_connect_provider",
}

# Deleting any of these is always high risk, even though non-destructive
# changes to them might not be (e.g. an EFS tag change is fine; deleting
# the EFS filesystem is not).
_STATEFUL_TYPES = {
    "aws_efs_file_system",
    "aws_dynamodb_table",
    "aws_s3_bucket",
    "aws_db_instance",
    "aws_sqs_queue",
    "aws_secretsmanager_secret",
}

# Attribute-only changes on these types are safe to auto-apply — matches
# "in-bounds autoscaling" from the build guide. Anything beyond these
# specific attributes on these types falls through to the default rule.
_AUTOSCALING_SAFE_ATTRS = {"desired_count", "desired_capacity"}
_AUTOSCALING_TYPES = {"aws_ecs_service", "aws_autoscaling_group"}


def classify(change: ResourceChange) -> Classification:
    if change.resource_type in _ALWAYS_HIGH_RISK_TYPES:
        return Classification(
            risk_score=90,
            auto_apply=False,
            summary=f"{change.resource_type} change ({', '.join(change.actions)}) always requires approval",
            matched_rule="always_high_risk_type",
        )

    if change.is_destroy and change.resource_type in _STATEFUL_TYPES:
        return Classification(
            risk_score=95,
            auto_apply=False,
            summary=f"Deletion of stateful resource {change.address}",
            matched_rule="stateful_deletion",
        )

    if change.is_tags_only:
        return Classification(
            risk_score=10,
            auto_apply=True,
            summary=f"Tag-only change on {change.address}",
            matched_rule="tags_only",
        )

    if (
        change.resource_type in _AUTOSCALING_TYPES
        and set(change.changed_attributes.keys()).issubset(_AUTOSCALING_SAFE_ATTRS)
        and not change.is_destroy
    ):
        return Classification(
            risk_score=15,
            auto_apply=True,
            summary=f"In-bounds scaling change on {change.address}",
            matched_rule="autoscaling_in_bounds",
        )

    # Default: unclassified changes are conservative — always require a
    # human, moderate risk score rather than assuming either extreme.
    return Classification(
        risk_score=50,
        auto_apply=False,
        summary=f"Unclassified change on {change.address} ({', '.join(change.actions)}): "
        f"{', '.join(change.changed_attributes.keys()) or 'no attribute diff available'}",
        matched_rule="default_conservative",
    )


def enforce_hard_ceiling(classification: Classification) -> Classification:
    """Applied by the caller after classify() — a risk score at or above
    the configured threshold can never auto-apply, regardless of which
    rule matched. This is the ceiling mentioned in config.py; it lives
    here so both scan and any future re-classification path use the same
    enforcement."""
    if classification.risk_score >= settings.high_risk_threshold and classification.auto_apply:
        return classification.model_copy(update={"auto_apply": False})
    return classification
