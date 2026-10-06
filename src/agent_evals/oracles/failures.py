"""Stable structured failure-code projection for deterministic oracle results."""

from __future__ import annotations

from dataclasses import dataclass

from agent_evals.oracles.codes import (
    OracleFailureCode,
    classify_legacy_oracle_reason,
)
from agent_evals.oracles.deterministic import OracleResult

__all__ = ["OracleFailure", "OracleFailureCode", "structured_oracle_failures"]


@dataclass(frozen=True, slots=True)
class OracleFailure:
    code: OracleFailureCode
    reason: str


def structured_oracle_failures(result: OracleResult) -> tuple[OracleFailure, ...]:
    """Expose stable emitted codes, with classification fallback for historical/manual results."""

    if type(result) is not OracleResult:
        raise ValueError("structured failure projection requires an exact OracleResult")
    codes = (
        result.failure_codes
        if len(result.failure_codes) == len(result.reasons)
        else tuple(classify_legacy_oracle_reason(result.name, reason) for reason in result.reasons)
    )
    return tuple(
        OracleFailure(code=code, reason=reason)
        for code, reason in zip(codes, result.reasons, strict=True)
    )
