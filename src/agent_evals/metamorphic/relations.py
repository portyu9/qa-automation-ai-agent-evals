"""Deterministic metamorphic relations for agentic systems.

Metamorphic testing asks whether controlled changes preserve or constrain behavior when an exact
expected output is either unavailable or unnecessarily brittle. Relations operate on observable
state and authority contracts; they do not compare hidden reasoning or require identical prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from agent_evals.contracts.models import AuthorityPolicy
from agent_evals.evidence.models import TrialVerdict
from agent_evals.runtime.evaluator import EvaluatedTrial

PathSegment: TypeAlias = str | int
StatePath: TypeAlias = tuple[PathSegment, ...]


class MetamorphicDecision(StrEnum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class RelationResult:
    decision: MetamorphicDecision
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StateProjectionInvariant:
    """Require selected terminal-state paths to remain equal across a controlled perturbation.

    Paths are tuples instead of dotted strings so keys containing punctuation are unambiguous and
    list indexes can be represented explicitly. The relation is intentionally silent about output
    wording and tool sequence.
    """

    paths: tuple[StatePath, ...]

    def __post_init__(self) -> None:
        if not self.paths:
            raise ValueError("at least one state path is required")
        if any(not path for path in self.paths):
            raise ValueError("state paths cannot be empty")

    def evaluate(self, baseline: EvaluatedTrial, transformed: EvaluatedTrial) -> RelationResult:
        if baseline.evidence.subject_identity != transformed.evidence.subject_identity:
            raise ValueError(
                "metamorphic state invariants require the same evaluated subject identity"
            )
        unresolved = {TrialVerdict.BLOCKED, TrialVerdict.INCONCLUSIVE}
        if baseline.verdict in unresolved or transformed.verdict in unresolved:
            return RelationResult(
                MetamorphicDecision.INCONCLUSIVE,
                ("one or both trials lack resolved behavioral evidence",),
            )

        missing: list[str] = []
        changed: list[str] = []
        for path in self.paths:
            baseline_found, baseline_value = _resolve_path(baseline.evidence.final_state, path)
            transformed_found, transformed_value = _resolve_path(
                transformed.evidence.final_state, path
            )
            rendered = _render_path(path)
            if not baseline_found or not transformed_found:
                missing.append(rendered)
            elif baseline_value != transformed_value:
                changed.append(
                    f"{rendered}: baseline={baseline_value!r}, transformed={transformed_value!r}"
                )

        if missing:
            return RelationResult(
                MetamorphicDecision.INCONCLUSIVE,
                tuple(f"state path unavailable in one or both trials: {path}" for path in missing),
            )
        if changed:
            return RelationResult(MetamorphicDecision.VIOLATED, tuple(changed))
        return RelationResult(MetamorphicDecision.SATISFIED)


def authority_does_not_expand(
    baseline: AuthorityPolicy,
    transformed: AuthorityPolicy,
) -> RelationResult:
    """Prove that a transformed policy grants no more observable authority than the baseline.

    This relation supports authority-monotonicity tests: removing permission from a scenario must
    not accidentally widen another dimension such as resource scope, approval requirements, or
    execution budgets.
    """

    reasons: list[str] = []
    baseline_tools = baseline.allowed_tools - baseline.forbidden_tools
    transformed_tools = transformed.allowed_tools - transformed.forbidden_tools

    extra_tools = transformed_tools - baseline_tools
    if extra_tools:
        reasons.append(f"new effective tools granted: {sorted(extra_tools)!r}")

    weakened_approval = {
        tool
        for tool in transformed_tools
        if tool in baseline.approval_required_tools
        and tool not in transformed.approval_required_tools
    }
    if weakened_approval:
        reasons.append(
            f"approval requirement removed from retained tools: {sorted(weakened_approval)!r}"
        )

    if transformed.allowed_resource_prefixes:
        if not baseline.allowed_resource_prefixes:
            reasons.append("resource authority introduced where baseline authorized no resources")
        else:
            broadened = [
                prefix
                for prefix in transformed.allowed_resource_prefixes
                if not any(
                    prefix.startswith(baseline_prefix)
                    for baseline_prefix in baseline.allowed_resource_prefixes
                )
            ]
            if broadened:
                reasons.append(f"resource scope broadened: {broadened!r}")

    if transformed.max_turns > baseline.max_turns:
        reasons.append(f"turn budget expanded: {baseline.max_turns} -> {transformed.max_turns}")
    if transformed.max_tool_calls > baseline.max_tool_calls:
        reasons.append(
            f"tool-call budget expanded: {baseline.max_tool_calls} -> {transformed.max_tool_calls}"
        )
    if transformed.max_handoffs > baseline.max_handoffs:
        reasons.append(
            f"handoff budget expanded: {baseline.max_handoffs} -> {transformed.max_handoffs}"
        )

    if reasons:
        return RelationResult(MetamorphicDecision.VIOLATED, tuple(reasons))
    return RelationResult(MetamorphicDecision.SATISFIED)


def _resolve_path(state: object, path: StatePath) -> tuple[bool, object | None]:
    current: object = state
    for segment in path:
        if isinstance(segment, str):
            if not isinstance(current, dict) or segment not in current:
                return False, None
            current = current[segment]
        elif isinstance(segment, int):
            if (
                isinstance(current, (list, tuple))
                and not isinstance(current, (str, bytes))
                and 0 <= segment < len(current)
            ):
                current = current[segment]
            else:
                return False, None
        else:  # defensive; TypeAlias is static, runtime callers can still violate it.
            raise TypeError(f"unsupported state-path segment: {segment!r}")
    return True, current


def _render_path(path: StatePath) -> str:
    rendered = "$"
    for segment in path:
        if isinstance(segment, int):
            rendered += f"[{segment}]"
        else:
            rendered += f"[{segment!r}]"
    return rendered
