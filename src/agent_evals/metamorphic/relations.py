"""Deterministic metamorphic relations for agentic systems.

Metamorphic testing asks whether controlled changes preserve or constrain behavior when an exact
expected output is either unavailable or unnecessarily brittle. Relations operate on observable
state and authority contracts; they do not compare hidden reasoning or require identical prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from agent_evals.contracts.models import AuthorityPolicy, HandoffAuthorityGrant
from agent_evals.contracts.resource import ResourceScope
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
    not accidentally widen another dimension such as resource scope, approval requirements,
    execution budgets, or delegated handoff authority.
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

    if transformed.allowed_resource_scopes:
        if not baseline.allowed_resource_scopes:
            reasons.append("resource authority introduced where baseline authorized no resources")
        else:
            broadened = _broadened_resource_scopes(
                baseline.allowed_resource_scopes,
                transformed.allowed_resource_scopes,
            )
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

    reasons.extend(_delegated_authority_expansion_reasons(baseline, transformed))

    if reasons:
        return RelationResult(MetamorphicDecision.VIOLATED, tuple(reasons))
    return RelationResult(MetamorphicDecision.SATISFIED)


def _delegated_authority_expansion_reasons(
    baseline: AuthorityPolicy,
    transformed: AuthorityPolicy,
) -> tuple[str, ...]:
    """Return structural delegated-authority changes that cannot prove monotonic attenuation.

    Legacy single-authority policy is the least restrictive handoff mode: adding a validated
    handoff graph constrains that mode, while removing an existing graph removes path-local
    attenuation. When both policies use graphs, every transformed transition must already exist in
    the baseline and each retained grant must be no broader than its baseline counterpart.
    """
    if not baseline.has_handoff_authority:
        return ()
    if not transformed.has_handoff_authority:
        return ("delegated handoff attenuation removed from transformed authority",)

    reasons: list[str] = []
    if transformed.root_agent != baseline.root_agent:
        reasons.append(
            "delegated handoff root identity changed: "
            f"{baseline.root_agent!r} -> {transformed.root_agent!r}"
        )

    baseline_grants = {grant.transition: grant for grant in baseline.handoff_grants}
    transformed_grants = {grant.transition: grant for grant in transformed.handoff_grants}
    new_transitions = sorted(transformed_grants.keys() - baseline_grants.keys())
    if new_transitions:
        reasons.append(f"new delegated handoff transitions granted: {new_transitions!r}")

    for transition in sorted(transformed_grants.keys() & baseline_grants.keys()):
        baseline_grant = baseline_grants[transition]
        transformed_grant = transformed_grants[transition]
        reasons.extend(_grant_expansion_reasons(baseline_grant, transformed_grant))

    return tuple(reasons)


def _grant_expansion_reasons(
    baseline: HandoffAuthorityGrant,
    transformed: HandoffAuthorityGrant,
) -> tuple[str, ...]:
    transition = f"{baseline.source_agent!r} -> {baseline.target_agent!r}"
    reasons: list[str] = []

    extra_tools = transformed.allowed_tools - baseline.allowed_tools
    if extra_tools:
        reasons.append(f"delegated tools broadened for {transition}: {sorted(extra_tools)!r}")

    retained_tools = transformed.allowed_tools & baseline.allowed_tools
    weakened_approval = (
        baseline.additional_approval_required_tools & retained_tools
    ) - transformed.additional_approval_required_tools
    if weakened_approval:
        reasons.append(
            "delegated approval requirement removed for retained tools on "
            f"{transition}: {sorted(weakened_approval)!r}"
        )

    broadened_scopes = _broadened_resource_scopes(
        baseline.allowed_resource_scopes,
        transformed.allowed_resource_scopes,
    )
    if broadened_scopes:
        reasons.append(f"delegated resource scope broadened for {transition}: {broadened_scopes!r}")

    if transformed.max_tool_calls > baseline.max_tool_calls:
        reasons.append(
            "delegated tool-call budget expanded for "
            f"{transition}: {baseline.max_tool_calls} -> {transformed.max_tool_calls}"
        )
    if transformed.max_handoffs > baseline.max_handoffs:
        reasons.append(
            "delegated handoff budget expanded for "
            f"{transition}: {baseline.max_handoffs} -> {transformed.max_handoffs}"
        )
    return tuple(reasons)


def _broadened_resource_scopes(
    baseline: tuple[ResourceScope, ...],
    transformed: tuple[ResourceScope, ...],
) -> list[str]:
    return [
        scope.canonical_json
        for scope in transformed
        if not any(parent.contains_scope(scope) for parent in baseline)
    ]


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
