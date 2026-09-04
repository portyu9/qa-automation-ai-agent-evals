from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.authority import (
    EffectiveAuthority,
    HandoffPathState,
    advance_handoff,
    attenuate_authority,
    event_agent_identity,
    validated_handoff_state_before,
)
from agent_evals.contracts.models import (
    ApprovalDecision,
    ApprovalIntentSpec,
    AuthorityPolicy,
    EvaluationScenario,
    HandoffAuthorityGrant,
    ScenarioKind,
)
from agent_evals.evidence.approval_intent import (
    ApprovalIntentError,
    ApprovalIntentReceipt,
    canonical_arguments_sha256,
    parse_approval_intent_event,
    verify_approval_intent,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

_IDENTITY = "d" * 64
_AGENT = "Approval agent"
_TOOL = "refund"
_CALL = "call-refund"
_ARGS = '{"order_id":"42"}'


def contract(decision: ApprovalDecision = ApprovalDecision.APPROVE) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id=f"approval.fail-closed.{decision.value}",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Exercise exact approval-intent failure semantics.",
        authority=AuthorityPolicy(
            allowed_tools=frozenset({_TOOL}),
            approval_required_tools=frozenset({_TOOL}),
        ),
        approval_intent=ApprovalIntentSpec(
            agent=_AGENT,
            tool=_TOOL,
            decision=decision,
        ),
    )


def event(sequence: int, kind: EvidenceKind, **payload: object) -> EvidenceEvent:
    return EvidenceEvent(sequence=sequence, kind=kind, source="test", payload=payload)


def request(sequence: int = 0) -> EvidenceEvent:
    return event(
        sequence,
        EvidenceKind.APPROVAL_REQUEST,
        agent=_AGENT,
        tool=_TOOL,
        call_id=_CALL,
        arguments=_ARGS,
    )


def execution(sequence: int) -> EvidenceEvent:
    return event(
        sequence,
        EvidenceKind.TOOL_REQUEST,
        agent=_AGENT,
        tool=_TOOL,
        call_id=_CALL,
        arguments=_ARGS,
    )


def result(
    sequence: int,
    *,
    agent: str = _AGENT,
    call_id: str = _CALL,
    approval_rejected: bool | None = None,
) -> EvidenceEvent:
    payload: dict[str, object] = {"agent": agent, "call_id": call_id, "output": "done"}
    if approval_rejected is not None:
        payload["approval_rejected"] = approval_rejected
    return event(sequence, EvidenceKind.TOOL_RESULT, **payload)


def receipt(
    scenario: EvaluationScenario,
    *,
    request_sequence: int = 0,
) -> ApprovalIntentReceipt:
    state = HandoffPathState.from_policy(scenario.authority)
    return ApprovalIntentReceipt.create(
        scenario=scenario,
        agent=_AGENT,
        tool=_TOOL,
        call_id=_CALL,
        arguments=_ARGS,
        resource=None,
        authority_epoch=state.epoch,
        authority_path_sha256=state.path_sha256,
        approval_request_sequence=request_sequence,
    )


def evidence(scenario: EvaluationScenario, *events: EvidenceEvent) -> TrialEvidence:
    return TrialEvidence(
        trial_id="approval-fail-closed",
        subject_identity=_IDENTITY,
        scenario_identity=scenario.identity,
        events=events,
    )


def test_approval_contract_rejects_unstable_or_non_required_targets() -> None:
    with pytest.raises(ValidationError, match="surrounding whitespace"):
        ApprovalIntentSpec(agent=" Approval agent", tool=_TOOL, decision=ApprovalDecision.APPROVE)

    with pytest.raises(ValidationError, match="inside root scenario authority"):
        EvaluationScenario(
            scenario_id="approval.fail-closed.unauthorized",
            revision="1",
            kind=ScenarioKind.SECURITY,
            objective="Reject an approval target outside authority.",
            approval_intent=ApprovalIntentSpec(
                agent=_AGENT,
                tool=_TOOL,
                decision=ApprovalDecision.APPROVE,
            ),
        )

    with pytest.raises(ValidationError, match="approval-required"):
        EvaluationScenario(
            scenario_id="approval.fail-closed.not-required",
            revision="1",
            kind=ScenarioKind.SECURITY,
            objective="Reject a target that does not require approval.",
            authority=AuthorityPolicy(allowed_tools=frozenset({_TOOL})),
            approval_intent=ApprovalIntentSpec(
                agent=_AGENT,
                tool=_TOOL,
                decision=ApprovalDecision.APPROVE,
            ),
        )


def test_receipt_creation_and_shape_fail_closed() -> None:
    no_intent = EvaluationScenario(
        scenario_id="approval.fail-closed.no-intent",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="No stronger approval is configured.",
    )
    state = HandoffPathState.from_policy(no_intent.authority)
    with pytest.raises(ApprovalIntentError, match="does not declare"):
        ApprovalIntentReceipt.create(
            scenario=no_intent,
            agent=_AGENT,
            tool=_TOOL,
            call_id=_CALL,
            arguments=_ARGS,
            resource=None,
            authority_epoch=0,
            authority_path_sha256=state.path_sha256,
            approval_request_sequence=0,
        )

    with pytest.raises(ApprovalIntentError, match="non-empty string arguments"):
        canonical_arguments_sha256("")

    scenario = contract()
    valid = receipt(scenario)
    tampered = valid.model_dump(mode="json")
    tampered["agent"] = "Different agent"
    with pytest.raises(ValidationError, match="root mismatch"):
        ApprovalIntentReceipt.model_validate(tampered)

    unstable_resource = valid.model_dump(mode="json")
    unstable_resource["resource"] = " tenant/7/refunds/42"
    with pytest.raises(ValidationError, match="stable non-empty"):
        ApprovalIntentReceipt.model_validate(unstable_resource)

    with pytest.raises(ApprovalIntentError, match="not approval-decision"):
        parse_approval_intent_event(event(0, EvidenceKind.OUTPUT, output="x"))
    with pytest.raises(ApprovalIntentError, match="exactly one receipt"):
        parse_approval_intent_event(
            event(
                0, EvidenceKind.APPROVAL_DECISION, receipt=valid.model_dump(mode="json"), extra=True
            )
        )


def test_verifier_rejects_scenario_and_decision_envelope_drift() -> None:
    scenario = contract()
    decision = receipt(scenario).to_event(sequence=1, source="evaluator")
    wrong_identity = TrialEvidence(
        trial_id="wrong-scenario",
        subject_identity=_IDENTITY,
        scenario_identity="e" * 64,
        events=(request(), decision),
    )
    with pytest.raises(ApprovalIntentError, match="does not match"):
        verify_approval_intent(scenario, wrong_identity)

    duplicate = evidence(
        scenario,
        request(),
        decision,
        receipt(scenario).to_event(sequence=2, source="evaluator"),
    )
    with pytest.raises(ApprovalIntentError, match="exactly one decision"):
        verify_approval_intent(scenario, duplicate)

    wrong_request_kind = evidence(
        scenario,
        execution(0),
        decision,
    )
    with pytest.raises(ApprovalIntentError, match="approval-request event"):
        verify_approval_intent(scenario, wrong_request_kind)

    no_intent = EvaluationScenario(
        scenario_id="approval.fail-closed.unexpected-decision",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Reject stronger evidence when no stronger scenario exists.",
    )
    unexpected = TrialEvidence(
        trial_id="unexpected-decision",
        subject_identity=_IDENTITY,
        scenario_identity=no_intent.identity,
        events=(decision.model_copy(update={"sequence": 0}),),
    )
    with pytest.raises(ApprovalIntentError, match="scenario has no approval intent"):
        verify_approval_intent(no_intent, unexpected)


def test_approve_requires_one_exact_resumed_request_and_result() -> None:
    scenario = contract()
    decision = receipt(scenario).to_event(sequence=1, source="evaluator")

    no_request = evidence(scenario, request(), decision, result(2))
    with pytest.raises(ApprovalIntentError, match="no matching resumed tool request"):
        verify_approval_intent(scenario, no_request)

    duplicate_request = evidence(
        scenario,
        request(),
        decision,
        execution(2),
        execution(3),
        result(4),
    )
    with pytest.raises(ApprovalIntentError, match="multiple resumed tool requests"):
        verify_approval_intent(scenario, duplicate_request)

    no_result = evidence(scenario, request(), decision, execution(2))
    with pytest.raises(ApprovalIntentError, match="exactly one matching resumed tool result"):
        verify_approval_intent(scenario, no_result)

    wrong_result_agent = evidence(
        scenario,
        request(),
        decision,
        execution(2),
        result(3, agent="Other agent"),
    )
    with pytest.raises(ApprovalIntentError, match="result agent identity"):
        verify_approval_intent(scenario, wrong_result_agent)

    rejection_marked = evidence(
        scenario,
        request(),
        decision,
        execution(2),
        result(3, approval_rejected=True),
    )
    with pytest.raises(ApprovalIntentError, match="rejection-marked"):
        verify_approval_intent(scenario, rejection_marked)


def test_reject_requires_explicit_matching_rejection_result() -> None:
    scenario = contract(ApprovalDecision.REJECT)
    decision = receipt(scenario).to_event(sequence=1, source="evaluator")

    unmarked = evidence(scenario, request(), decision, result(2))
    with pytest.raises(ApprovalIntentError, match="explicit rejection marker"):
        verify_approval_intent(scenario, unmarked)

    wrong_result_call = evidence(
        scenario,
        request(),
        decision,
        result(2, call_id="different-call", approval_rejected=True),
    )
    with pytest.raises(ApprovalIntentError, match="exactly one matching continuation result"):
        verify_approval_intent(scenario, wrong_result_call)


def test_handoff_helpers_reject_invalid_transitions_without_advancing() -> None:
    policy = AuthorityPolicy(
        allowed_tools=frozenset({"read"}),
        approval_required_tools=frozenset({"read"}),
        allowed_resource_prefixes=("tenant/7/",),
        root_agent="Root",
        max_handoffs=1,
        handoff_grants=(
            HandoffAuthorityGrant(
                source_agent="Root",
                target_agent="Child",
                allowed_tools=frozenset({"read"}),
                allowed_resource_prefixes=("tenant/7/orders/",),
                max_handoffs=0,
            ),
        ),
    )
    state = HandoffPathState.from_policy(policy)

    with pytest.raises(ValueError, match="requires HANDOFF"):
        advance_handoff(policy, state, event(0, EvidenceKind.OUTPUT, output="x"))

    malformed = event(0, EvidenceKind.HANDOFF, source_agent="", target_agent="Child")
    same, errors = advance_handoff(policy, state, malformed)
    assert same == state
    assert errors

    wrong_source = event(0, EvidenceKind.HANDOFF, source_agent="Other", target_agent="Child")
    same, errors = advance_handoff(policy, state, wrong_source)
    assert same == state
    assert errors

    ungranted = event(0, EvidenceKind.HANDOFF, source_agent="Root", target_agent="Other")
    same, errors = advance_handoff(policy, state, ungranted)
    assert same == state
    assert errors

    valid = event(0, EvidenceKind.HANDOFF, source_agent="Root", target_agent="Child")
    advanced, errors = advance_handoff(policy, state, valid)
    assert not errors
    assert advanced.active_agent == "Child"
    assert advanced.epoch == 1
    assert advanced.path_sha256 != state.path_sha256

    assert event_agent_identity(7) is None
    assert event_agent_identity(" Child ") is None
    assert event_agent_identity("Child") == "Child"

    legacy = AuthorityPolicy(allowed_tools=frozenset({"read"}))
    replayed = validated_handoff_state_before(
        legacy,
        (event(0, EvidenceKind.OUTPUT, output="ignored"),),
        1,
    )
    assert replayed.epoch == 0


def test_attenuation_reports_tool_resource_and_budget_reexpansion() -> None:
    source = EffectiveAuthority(
        allowed_tools=frozenset({"read"}),
        approval_required_tools=frozenset({"read"}),
        allowed_resource_prefixes=("tenant/7/orders/",),
        max_tool_calls=1,
        max_handoffs=1,
    )
    grant = HandoffAuthorityGrant(
        source_agent="Child",
        target_agent="Worker",
        allowed_tools=frozenset({"read", "write"}),
        allowed_resource_prefixes=("tenant/8/",),
        max_tool_calls=2,
        max_handoffs=2,
    )

    child, errors = attenuate_authority(source=source, grant=grant)

    assert child.allowed_tools == frozenset({"read", "write"})
    assert len(errors) == 4
    assert any("tool authority" in reason for reason in errors)
    assert any("resource authority" in reason for reason in errors)
    assert any("tool-call budget" in reason for reason in errors)
    assert any("handoff budget" in reason for reason in errors)
