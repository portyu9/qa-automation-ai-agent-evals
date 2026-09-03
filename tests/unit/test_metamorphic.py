from __future__ import annotations

import pytest

from agent_evals.contracts.models import AuthorityPolicy
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.metamorphic.relations import (
    MetamorphicDecision,
    StateProjectionInvariant,
    authority_does_not_expand,
)
from agent_evals.runtime.evaluator import EvaluatedTrial

IDENTITY = "c" * 64
SCENARIO = "d" * 64


def trial(
    state: dict[str, object],
    verdict: TrialVerdict = TrialVerdict.PASS,
) -> EvaluatedTrial:
    return EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id="t",
            subject_identity=IDENTITY,
            scenario_identity=SCENARIO,
            final_state=state,
        ),
        oracle_results=(),
        verdict=verdict,
    )


def test_state_projection_ignores_unconstrained_output_and_compares_selected_state() -> None:
    relation = StateProjectionInvariant(paths=(("account", "status"), ("items", 0, "id")))
    baseline = trial(
        {"account": {"status": "active"}, "items": [{"id": 7}], "noise": "a"}
    )
    transformed = trial(
        {"account": {"status": "active"}, "items": [{"id": 7}], "noise": "b"}
    )
    assert relation.evaluate(baseline, transformed).decision is MetamorphicDecision.SATISFIED


def test_state_projection_reports_changed_protected_state() -> None:
    relation = StateProjectionInvariant(paths=(("account", "status"),))
    result = relation.evaluate(
        trial({"account": {"status": "active"}}),
        trial({"account": {"status": "closed"}}),
    )
    assert result.decision is MetamorphicDecision.VIOLATED


def test_state_projection_preserves_unresolved_evidence_as_inconclusive() -> None:
    relation = StateProjectionInvariant(paths=(("account", "status"),))
    result = relation.evaluate(
        trial({"account": {"status": "active"}}),
        trial({}, TrialVerdict.BLOCKED),
    )
    assert result.decision is MetamorphicDecision.INCONCLUSIVE


def test_state_projection_refuses_cross_subject_comparison() -> None:
    relation = StateProjectionInvariant(paths=(("x",),))
    other = EvaluatedTrial(
        evidence=TrialEvidence(
            trial_id="other",
            subject_identity="e" * 64,
            scenario_identity=SCENARIO,
            final_state={"x": 1},
        ),
        oracle_results=(),
        verdict=TrialVerdict.PASS,
    )
    with pytest.raises(ValueError, match="same evaluated subject"):
        relation.evaluate(trial({"x": 1}), other)


def test_authority_monotonicity_accepts_narrower_policy() -> None:
    baseline = AuthorityPolicy(
        allowed_tools=frozenset({"read", "write"}),
        approval_required_tools=frozenset({"write"}),
        allowed_resource_prefixes=("tenant/7/",),
        max_turns=20,
        max_tool_calls=20,
        max_handoffs=5,
    )
    restricted = AuthorityPolicy(
        allowed_tools=frozenset({"read", "write"}),
        approval_required_tools=frozenset({"write"}),
        allowed_resource_prefixes=("tenant/7/orders/",),
        max_turns=10,
        max_tool_calls=10,
        max_handoffs=2,
    )
    assert (
        authority_does_not_expand(baseline, restricted).decision
        is MetamorphicDecision.SATISFIED
    )


def test_authority_monotonicity_detects_permission_laundering() -> None:
    baseline = AuthorityPolicy(
        allowed_tools=frozenset({"read", "write"}),
        approval_required_tools=frozenset({"write"}),
        allowed_resource_prefixes=("tenant/7/",),
        max_turns=10,
    )
    transformed = AuthorityPolicy(
        allowed_tools=frozenset({"read", "write", "export"}),
        allowed_resource_prefixes=("tenant/",),
        max_turns=20,
    )
    result = authority_does_not_expand(baseline, transformed)
    assert result.decision is MetamorphicDecision.VIOLATED
    assert any("new effective tools" in reason for reason in result.reasons)
    assert any("approval requirement removed" in reason for reason in result.reasons)
    assert any("resource scope broadened" in reason for reason in result.reasons)
    assert any("turn budget expanded" in reason for reason in result.reasons)
