"""Non-compensatory slice/family and operational-tail release gates."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from agent_evals.gates.release import GateDecision, GateResult, ReleaseGate, ReleasePolicy
from agent_evals.statistics.operational import OperationalInclusion, OperationalSummary
from agent_evals.statistics.reliability import ReliabilityReport

_MAX_LABEL = 160


@dataclass(frozen=True, slots=True)
class SliceEvidence:
    slice_id: str
    risk_family: str
    reliability: ReliabilityReport
    critical_violations: int = 0

    def __post_init__(self) -> None:
        _validate_label(self.slice_id, name="slice_id")
        _validate_label(self.risk_family, name="risk_family")
        if type(self.reliability) is not ReliabilityReport:
            raise ValueError("reliability must be an exact ReliabilityReport")
        self.reliability.validate()
        if type(self.critical_violations) is not int or self.critical_violations < 0:
            raise ValueError("critical_violations must be a non-negative exact integer")


@dataclass(frozen=True, slots=True)
class RiskFamilyResult:
    risk_family: str
    decision: GateDecision
    worst_slice: str
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_label(self.risk_family, name="risk_family")
        if type(self.decision) is not GateDecision:
            raise ValueError("decision must be an exact GateDecision")
        _validate_label(self.worst_slice, name="worst_slice")
        if type(self.reasons) is not tuple or any(type(item) is not str for item in self.reasons):
            raise ValueError("reasons must be an exact tuple of strings")


@dataclass(frozen=True, slots=True)
class SliceGateResult:
    decision: GateDecision
    worst_slice: str
    family_results: tuple[RiskFamilyResult, ...]
    reasons: tuple[str, ...]


class SliceReleaseGate:
    """Require every slice and every required risk family to close independently."""

    def __init__(
        self,
        policy: ReleasePolicy,
        *,
        required_risk_families: tuple[str, ...] = (),
    ) -> None:
        if type(policy) is not ReleasePolicy:
            raise ValueError("policy must be an exact ReleasePolicy")
        if type(required_risk_families) is not tuple:
            raise ValueError("required_risk_families must be an exact tuple")
        seen: set[str] = set()
        for family in required_risk_families:
            _validate_label(family, name="required risk family")
            if family in seen:
                raise ValueError("required risk families must be unique")
            seen.add(family)
        self._policy = policy
        self._required = required_risk_families

    def decide(self, slices: tuple[SliceEvidence, ...]) -> SliceGateResult:
        if type(slices) is not tuple or not slices:
            raise ValueError("slices must be a non-empty exact tuple")
        seen: set[str] = set()
        by_family: dict[str, list[tuple[SliceEvidence, GateResult]]] = {}
        all_results: list[tuple[SliceEvidence, GateResult]] = []
        gate = ReleaseGate(self._policy)
        for item in slices:
            if type(item) is not SliceEvidence:
                raise ValueError("slices must contain exact SliceEvidence values")
            if item.slice_id in seen:
                raise ValueError("slice identifiers must be unique")
            seen.add(item.slice_id)
            result = gate.decide(
                item.reliability,
                critical_violations=item.critical_violations,
            )
            all_results.append((item, result))
            by_family.setdefault(item.risk_family, []).append((item, result))

        worst = min(
            slices,
            key=lambda item: (
                item.reliability.wilson_low,
                item.reliability.success_rate,
                item.slice_id,
            ),
        )
        reasons: list[str] = []
        missing = sorted(set(self._required) - set(by_family))
        for family in missing:
            reasons.append(f"required risk family {family!r} has no slice evidence")

        family_results: list[RiskFamilyResult] = []
        for family in sorted(by_family):
            members = by_family[family]
            family_worst = min(
                members,
                key=lambda pair: (
                    pair[0].reliability.wilson_low,
                    pair[0].reliability.success_rate,
                    pair[0].slice_id,
                ),
            )[0]
            member_decisions = [result.decision for _, result in members]
            if GateDecision.REJECT in member_decisions:
                decision = GateDecision.REJECT
            elif GateDecision.INCONCLUSIVE in member_decisions:
                decision = GateDecision.INCONCLUSIVE
            else:
                decision = GateDecision.ACCEPT
            family_reasons = tuple(
                f"{item.slice_id}: {reason}"
                for item, result in members
                for reason in result.reasons
            )
            family_results.append(
                RiskFamilyResult(
                    risk_family=family,
                    decision=decision,
                    worst_slice=family_worst.slice_id,
                    reasons=family_reasons,
                )
            )
            reasons.extend(f"{family}: {reason}" for reason in family_reasons)

        any_reject = any(result.decision is GateDecision.REJECT for _, result in all_results)
        any_inconclusive = any(
            result.decision is GateDecision.INCONCLUSIVE for _, result in all_results
        )
        if any_reject:
            overall = GateDecision.REJECT
        elif any_inconclusive or missing:
            overall = GateDecision.INCONCLUSIVE
        else:
            overall = GateDecision.ACCEPT
        return SliceGateResult(
            decision=overall,
            worst_slice=worst.slice_id,
            family_results=tuple(family_results),
            reasons=tuple(reasons),
        )


@dataclass(frozen=True, slots=True)
class OperationalTailPolicy:
    minimum_samples: int = 20
    max_latency_p95_ms: float | None = None
    max_cost_p95_usd: float | None = None
    max_tool_calls_p99: int | None = None
    max_retries_p99: int | None = None
    allow_excluded_unresolved: bool = False

    def __post_init__(self) -> None:
        if type(self.minimum_samples) is not int or self.minimum_samples < 1:
            raise ValueError("minimum_samples must be a positive exact integer")
        for name in ("max_latency_p95_ms", "max_cost_p95_usd"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, float)
                or not isfinite(value)
                or value < 0.0
            ):
                raise ValueError(f"{name} must be None or a finite non-negative float")
        for name in ("max_tool_calls_p99", "max_retries_p99"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be None or a non-negative exact integer")
        if type(self.allow_excluded_unresolved) is not bool:
            raise ValueError("allow_excluded_unresolved must be an exact bool")
        if all(
            value is None
            for value in (
                self.max_latency_p95_ms,
                self.max_cost_p95_usd,
                self.max_tool_calls_p99,
                self.max_retries_p99,
            )
        ):
            raise ValueError("operational tail policy requires at least one threshold")


class OperationalReleaseGate:
    def __init__(self, policy: OperationalTailPolicy) -> None:
        if type(policy) is not OperationalTailPolicy:
            raise ValueError("policy must be an exact OperationalTailPolicy")
        self._policy = policy

    def decide(self, summary: OperationalSummary) -> GateResult:
        if type(summary) is not OperationalSummary:
            raise ValueError("summary must be an exact OperationalSummary")
        p = self._policy
        failures: list[str] = []
        uncertainty: list[str] = []
        if summary.included_attempts < p.minimum_samples:
            uncertainty.append(
                f"included operational samples {summary.included_attempts} "
                f"are below required {p.minimum_samples}"
            )
        if (
            summary.inclusion is OperationalInclusion.RESOLVED_ONLY
            and not p.allow_excluded_unresolved
            and (summary.excluded_blocked or summary.excluded_inconclusive)
        ):
            uncertainty.append(
                "resolved-only operational summary excluded "
                f"{summary.excluded_blocked} blocked and "
                f"{summary.excluded_inconclusive} inconclusive attempts"
            )
        if p.max_latency_p95_ms is not None and summary.latency_p95_ms > p.max_latency_p95_ms:
            failures.append(
                f"latency p95 {summary.latency_p95_ms:.4f} ms exceeds "
                f"{p.max_latency_p95_ms:.4f} ms"
            )
        if p.max_cost_p95_usd is not None and summary.cost_p95_usd > p.max_cost_p95_usd:
            failures.append(
                f"cost p95 {summary.cost_p95_usd:.8f} USD exceeds "
                f"{p.max_cost_p95_usd:.8f} USD"
            )
        if p.max_tool_calls_p99 is not None and summary.tool_calls_p99 > p.max_tool_calls_p99:
            failures.append(
                f"tool-call p99 {summary.tool_calls_p99} exceeds {p.max_tool_calls_p99}"
            )
        if p.max_retries_p99 is not None and summary.retries_p99 > p.max_retries_p99:
            failures.append(f"retry p99 {summary.retries_p99} exceeds {p.max_retries_p99}")

        if failures:
            return GateResult(GateDecision.REJECT, tuple(failures + uncertainty))
        if uncertainty:
            return GateResult(GateDecision.INCONCLUSIVE, tuple(uncertainty))
        return GateResult(GateDecision.ACCEPT, ())


def _validate_label(value: object, *, name: str) -> None:
    if type(value) is not str:
        raise ValueError(f"{name} must be an exact string")
    if (
        not value
        or len(value) > _MAX_LABEL
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(
            f"{name} must contain 1..{_MAX_LABEL} trimmed characters without controls"
        )
