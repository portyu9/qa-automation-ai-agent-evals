"""Stable structured failure-code projection for deterministic oracle results."""

from __future__ import annotations

from dataclasses import dataclass
from agent_evals.oracles.deterministic import OracleResult


from agent_evals.oracles.codes import (
    OracleFailureCode,
    classify_legacy_oracle_reason,
)
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
    codes = (
        result.failure_codes
        if len(result.failure_codes) == len(result.reasons)
        else tuple(
            classify_legacy_oracle_reason(result.name, reason)
            for reason in result.reasons
        )
    )
    return tuple(
        OracleFailure(code=code, reason=reason)
        for code, reason in zip(codes, result.reasons, strict=True)
    )

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
