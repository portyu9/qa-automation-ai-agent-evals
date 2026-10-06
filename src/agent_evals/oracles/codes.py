"""Stable deterministic-oracle failure codes independent of human-readable reason text."""

from __future__ import annotations

from enum import StrEnum


class OracleFailureCode(StrEnum):
    OUTCOME_REQUIRED_MISSING = "outcome.required_missing"
    OUTCOME_REQUIRED_MISMATCH = "outcome.required_mismatch"
    OUTCOME_FORBIDDEN_OBSERVED = "outcome.forbidden_observed"
    POLICY_APPROVAL = "policy.approval"
    POLICY_AUTHORITY = "policy.authority"
    POLICY_RESOURCE = "policy.resource"
    POLICY_HANDOFF = "policy.handoff"
    POLICY_BUDGET = "policy.budget"
    POLICY_EXPLICIT = "policy.explicit"
    ORACLE_UNCLASSIFIED = "oracle.unclassified"


def classify_legacy_oracle_reason(name: str, reason: str) -> OracleFailureCode:
    """Best-effort classification for historical/manual OracleResult values without codes."""

    if name == "outcome":
        if "is missing from terminal state" in reason:
            return OracleFailureCode.OUTCOME_REQUIRED_MISSING
        if reason.startswith("required outcome "):
            return OracleFailureCode.OUTCOME_REQUIRED_MISMATCH
        if reason.startswith("forbidden outcome "):
            return OracleFailureCode.OUTCOME_FORBIDDEN_OBSERVED
        return OracleFailureCode.ORACLE_UNCLASSIFIED

    if name == "policy":
        lowered = reason.lower()
        if "approval" in lowered:
            return OracleFailureCode.POLICY_APPROVAL
        if "resource" in lowered:
            return OracleFailureCode.POLICY_RESOURCE
        if "handoff" in lowered:
            return OracleFailureCode.POLICY_HANDOFF
        if "budget exceeded" in lowered or "tool-call budget" in lowered:
            return OracleFailureCode.POLICY_BUDGET
        if (
            "unauthorized" in lowered
            or "non-active agent" in lowered
            or "generating-agent" in lowered
        ):
            return OracleFailureCode.POLICY_AUTHORITY
        return OracleFailureCode.POLICY_EXPLICIT

    return OracleFailureCode.ORACLE_UNCLASSIFIED
