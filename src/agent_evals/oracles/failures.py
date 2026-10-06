"""Stable structured failure-code projection for deterministic oracle results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent_evals.oracles.deterministic import OracleResult


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


@dataclass(frozen=True, slots=True)
class OracleFailure:
    code: OracleFailureCode
    reason: str


def structured_oracle_failures(result: OracleResult) -> tuple[OracleFailure, ...]:
    """Project existing human-readable reasons into stable non-authorizing failure classes.

    Verdict and criticality stay owned by the original oracle. This function neither changes nor
    recomputes them; it only adds machine-stable classification for diagnostics/policy routing.
    """

    if type(result) is not OracleResult:
        raise ValueError("structured failure projection requires an exact OracleResult")
    return tuple(OracleFailure(code=_classify(result.name, reason), reason=reason) for reason in result.reasons)


def _classify(name: str, reason: str) -> OracleFailureCode:
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
        if "unauthorized" in lowered or "non-active agent" in lowered or "generating-agent" in lowered:
            return OracleFailureCode.POLICY_AUTHORITY
        return OracleFailureCode.POLICY_EXPLICIT

    return OracleFailureCode.ORACLE_UNCLASSIFIED
