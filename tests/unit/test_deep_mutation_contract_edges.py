from __future__ import annotations

import hashlib

import pytest

import agent_evals.adversarial.delivery as attack_delivery
import agent_evals.runtime.preconditions as preconditions
from agent_evals.adversarial.delivery import AttackDeliveryError
from agent_evals.authority import (
    EffectiveAuthority,
    HandoffPathState,
    advance_handoff,
    attenuate_authority,
    event_agent_identity,
    validated_handoff_epoch_before,
    validated_handoff_state_before,
)
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    HandoffAuthorityGrant,
    ScenarioKind,
)
from agent_evals.contracts.resource import ResourceScope
from agent_evals.evidence.approval_intent import ApprovalIntentError
from agent_evals.evidence.models import (
    EvidenceEvent,
    EvidenceKind,
    TrialEvidence,
    TrialVerdict,
)
from agent_evals.gates.release import GateDecision, ReleaseGate, ReleasePolicy
from agent_evals.mcp.delivery import ProtocolDeliveryError
from agent_evals.retrieval.verification import RetrievalDeliveryError
from agent_evals.runtime.preconditions import EvaluationPreconditionError
from agent_evals.side_effect.verification import SideEffectObservationError
from agent_evals.statistics.reliability import ReliabilityReport

_ROOT = "Root agent"
_CHILD = "Specialist agent"
_SUBJECT = "a" * 64


def _scope(*components: str) -> ResourceScope:
    return ResourceScope(domain="tenant", components=components)


def _grant(
    *,
    target: str = _CHILD,
    tools: frozenset[str] = frozenset({"read"}),
    scopes: tuple[ResourceScope, ...] = (_scope("7", "orders"),),
    max_tool_calls: int = 3,
    max_handoffs: int = 2,
) -> HandoffAuthorityGrant:
    return HandoffAuthorityGrant(
        source_agent=_ROOT,
        target_agent=target,
        allowed_tools=tools,
        allowed_resource_scopes=scopes,
        max_tool_calls=max_tool_calls,
        max_handoffs=max_handoffs,
    )


def _authority() -> AuthorityPolicy:
    return AuthorityPolicy(
        allowed_tools=frozenset({"read", "write"}),
        approval_required_tools=frozenset({"write"}),
        allowed_resource_scopes=(_scope("7"),),
        max_tool_calls=3,
        max_handoffs=2,
        root_agent=_ROOT,
        handoff_grants=(_grant(),),
    )


def _handoff(sequence: int, source: object, target: object) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=EvidenceKind.HANDOFF,
        source="test",
        payload={"source_agent": source, "target_agent": target},
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.edges",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Exercise mutation-sensitive trust-boundary semantics.",
        authority=AuthorityPolicy(),
    )


def _evidence(scenario: EvaluationScenario) -> TrialEvidence:
    return TrialEvidence(
        trial_id="mutation-edges",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
    )


@pytest.mark.parametrize("value", [None, 7, "", " Root agent ", "\t"])
def test_event_agent_identity_rejects_unstable_values(value: object) -> None:
    assert event_agent_identity(value) is None


def test_event_agent_identity_preserves_exact_stable_value() -> None:
    assert event_agent_identity(_ROOT) == _ROOT


def test_advance_handoff_rejects_wrong_event_kind_with_stable_diagnostic() -> None:
    state = HandoffPathState.from_policy(_authority())
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="test",
        payload={},
    )

    with pytest.raises(
        ValueError,
        match=r"^advance_handoff requires HANDOFF evidence$",
    ):
        advance_handoff(_authority(), state, event)


def test_advance_handoff_fail_closed_diagnostics_and_valid_transition() -> None:
    policy = _authority()
    state = HandoffPathState.from_policy(policy)

    malformed_state, malformed_reasons = advance_handoff(
        policy,
        state,
        _handoff(0, "", _CHILD),
    )
    assert malformed_state == state
    assert malformed_reasons == (
        "handoff evidence requires non-empty source_agent and target_agent identities "
        "while handoff authority is enabled",
    )

    wrong_state, wrong_reasons = advance_handoff(
        policy,
        state,
        _handoff(0, _CHILD, "Worker agent"),
    )
    assert wrong_state == state
    assert wrong_reasons == (
        "handoff source is not the currently active agent: "
        f"observed={_CHILD!r} active={_ROOT!r}",
    )

    denied_state, denied_reasons = advance_handoff(
        policy,
        state,
        _handoff(0, _ROOT, "Unknown agent"),
    )
    assert denied_state == state
    assert denied_reasons == (
        f"unauthorized handoff transition: {_ROOT!r} -> {'Unknown agent'!r}",
    )

    child_state, reasons = advance_handoff(policy, state, _handoff(0, _ROOT, _CHILD))
    assert reasons == ()
    assert child_state.root_agent == _ROOT
    assert child_state.active_agent == _CHILD
    assert child_state.epoch == 1
    assert child_state.transitions == ((_ROOT, _CHILD),)


def test_handoff_replay_counts_only_semantically_accepted_transitions() -> None:
    policy = _authority()
    events = (
        _handoff(0, _ROOT, "Unknown agent"),
        _handoff(1, _ROOT, _CHILD),
    )

    before_second = validated_handoff_state_before(policy, events, 1)
    after_second = validated_handoff_state_before(policy, events, 2)

    assert before_second.active_agent == _ROOT
    assert before_second.epoch == 0
    assert validated_handoff_epoch_before(policy, events, 1) == 0
    assert after_second.active_agent == _CHILD
    assert after_second.epoch == 1
    assert validated_handoff_epoch_before(policy, events, 2) == 1


def test_authority_attenuation_allows_equal_budgets_but_rejects_reexpansion() -> None:
    source = EffectiveAuthority(
        allowed_tools=frozenset({"read"}),
        approval_required_tools=frozenset(),
        allowed_resource_scopes=(_scope("7"),),
        max_tool_calls=3,
        max_handoffs=2,
    )
    equal_child, equal_reasons = attenuate_authority(
        source=source,
        grant=_grant(
            tools=frozenset({"read"}),
            scopes=(_scope("7", "orders"),),
            max_tool_calls=3,
            max_handoffs=2,
        ),
    )
    assert equal_reasons == ()
    assert equal_child.max_tool_calls == 3
    assert equal_child.max_handoffs == 2

    _, widened_budget_reasons = attenuate_authority(
        source=source,
        grant=_grant(
            tools=frozenset({"read"}),
            scopes=(_scope("7", "orders"),),
            max_tool_calls=4,
            max_handoffs=3,
        ),
    )
    assert widened_budget_reasons == (
        "handoff authority broadens source tool-call budget for transition "
        f"{_ROOT!r} -> {_CHILD!r}: 4 > 3",
        "handoff authority broadens source handoff budget for transition "
        f"{_ROOT!r} -> {_CHILD!r}: 3 > 2",
    )


def test_authority_attenuation_reports_tool_and_resource_reexpansion() -> None:
    source = EffectiveAuthority(
        allowed_tools=frozenset({"read"}),
        approval_required_tools=frozenset(),
        allowed_resource_scopes=(_scope("7"),),
        max_tool_calls=3,
        max_handoffs=2,
    )
    _, reasons = attenuate_authority(
        source=source,
        grant=_grant(
            tools=frozenset({"read", "write"}),
            scopes=(_scope("8"),),
        ),
    )

    assert len(reasons) == 2
    assert reasons[0].startswith(
        "handoff authority broadens source tool authority for transition "
    )
    assert reasons[1].startswith(
        "handoff authority broadens source resource authority for transition "
    )


@pytest.mark.parametrize(
    ("verifier_name", "error_type", "expected_source", "expected_code"),
    [
        (
            "verify_attack_delivery",
            AttackDeliveryError,
            "evaluator:attack-delivery",
            "attack_delivery_unverified",
        ),
        (
            "verify_protocol_delivery",
            ProtocolDeliveryError,
            "evaluator:protocol-delivery",
            "protocol_delivery_unverified",
        ),
        (
            "verify_retrieval_delivery",
            RetrievalDeliveryError,
            "evaluator:retrieval-delivery",
            "retrieval_delivery_unverified",
        ),
        (
            "verify_side_effect_observation",
            SideEffectObservationError,
            "evaluator:side-effect-observation",
            "side_effect_observation_unverified",
        ),
        (
            "verify_approval_intent",
            ApprovalIntentError,
            "evaluator:approval-intent",
            "approval_intent_unverified",
        ),
    ],
)
def test_pregrading_closure_preserves_structured_failure_provenance(
    monkeypatch: pytest.MonkeyPatch,
    verifier_name: str,
    error_type: type[ValueError],
    expected_source: str,
    expected_code: str,
) -> None:
    scenario = _scenario()
    evidence = _evidence(scenario)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise error_type("sentinel failure")

    monkeypatch.setattr(preconditions, verifier_name, fail)

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions.verify_pregrading_closure(scenario, evidence)

    assert captured.value.source == expected_source
    assert captured.value.code == expected_code
    assert captured.value.reason == "sentinel failure"
    assert str(captured.value) == "sentinel failure"


def test_evaluation_precondition_error_exposes_exact_structured_fields() -> None:
    error = EvaluationPreconditionError(
        source="evaluator:test",
        code="test_unverified",
        reason="sentinel failure",
    )

    assert error.source == "evaluator:test"
    assert error.code == "test_unverified"
    assert error.reason == "sentinel failure"
    assert str(error) == "sentinel failure"


def test_attack_delivery_canonical_bytes_and_domain_root_are_exact() -> None:
    value = {"z": 1, "a": "Ω"}
    expected = b'{"a":"\\u03a9","z":1}'

    assert attack_delivery._canonical_json_bytes(value) == expected
    assert attack_delivery._receipt_root(value) == hashlib.sha256(
        b"agent-evals/attack-delivery/v1\0" + expected
    ).hexdigest()


def test_attack_delivery_canonicalization_rejects_nonfinite_json() -> None:
    with pytest.raises(ValueError):
        attack_delivery._canonical_json_bytes({"value": float("nan")})


def test_attack_delivery_receipt_root_preserves_resource_limit_label() -> None:
    with pytest.raises(ValueError, match="attack delivery receipt material"):
        attack_delivery._receipt_root(object())


def _gate_policy(**overrides: object) -> ReleasePolicy:
    material: dict[str, object] = {
        "min_resolved_trials": 1,
        "min_success_rate": 0.0,
        "min_wilson_low": 0.0,
        "max_critical_violations": 0,
        "max_blocked_trials": 99,
        "max_inconclusive_trials": 99,
    }
    material.update(overrides)
    return ReleasePolicy.model_validate(material)


def test_release_gate_validation_errors_are_stable_and_fail_closed() -> None:
    gate = ReleaseGate(_gate_policy())
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS])

    with pytest.raises(
        ValueError,
        match=r"^report must be an exact ReliabilityReport$",
    ):
        gate.decide(object(), critical_violations=0)  # type: ignore[arg-type]
    with pytest.raises(
        ValueError,
        match=r"^critical_violations must be a non-negative integer$",
    ):
        gate.decide(report, critical_violations=True)
    with pytest.raises(
        ValueError,
        match=r"^critical_violations must be a non-negative integer$",
    ):
        gate.decide(report, critical_violations=-1)


def test_release_gate_threshold_equality_is_accepted() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS])
    gate = ReleaseGate(
        _gate_policy(
            min_success_rate=report.success_rate,
            min_wilson_low=report.wilson_low,
        )
    )

    result = gate.decide(report, critical_violations=0)
    assert result.decision is GateDecision.ACCEPT
    assert result.reasons == ()


def test_release_gate_reports_each_noncompensatory_and_uncertainty_boundary() -> None:
    half_success = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.FAIL]
    )
    rejected = ReleaseGate(_gate_policy(min_success_rate=0.75)).decide(
        half_success,
        critical_violations=1,
    )
    assert rejected.decision is GateDecision.REJECT
    assert rejected.reasons == (
        "critical violations 1 exceed maximum 0",
        "success rate 0.5000 is below 0.7500",
    )

    blocked_report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.BLOCKED]
    )
    blocked = ReleaseGate(_gate_policy(max_blocked_trials=0)).decide(
        blocked_report,
        critical_violations=0,
    )
    assert blocked.decision is GateDecision.INCONCLUSIVE
    assert blocked.reasons == ("blocked trials 1 exceed maximum 0",)

    inconclusive_report = ReliabilityReport.from_verdicts(
        [TrialVerdict.PASS, TrialVerdict.INCONCLUSIVE]
    )
    inconclusive = ReleaseGate(_gate_policy(max_inconclusive_trials=0)).decide(
        inconclusive_report,
        critical_violations=0,
    )
    assert inconclusive.decision is GateDecision.INCONCLUSIVE
    assert inconclusive.reasons == ("inconclusive trials 1 exceed maximum 0",)


def test_release_gate_resolved_count_and_wilson_uncertainty_are_exact() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.PASS])
    minimum_wilson = min(1.0, report.wilson_low + 0.01)
    gate = ReleaseGate(
        _gate_policy(
            min_resolved_trials=2,
            min_wilson_low=minimum_wilson,
        )
    )

    result = gate.decide(report, critical_violations=0)
    assert result.decision is GateDecision.INCONCLUSIVE
    assert result.reasons == (
        "resolved trial count 1 is below required 2",
        f"Wilson lower bound {report.wilson_low:.4f} is below {minimum_wilson:.4f}",
    )


def test_release_gate_zero_resolved_trials_preserve_uncertainty_not_failure() -> None:
    report = ReliabilityReport.from_verdicts([TrialVerdict.BLOCKED])
    gate = ReleaseGate(
        _gate_policy(
            min_resolved_trials=1,
            min_success_rate=1.0,
            min_wilson_low=1.0,
            max_blocked_trials=1,
        )
    )

    result = gate.decide(report, critical_violations=0)
    assert result.decision is GateDecision.INCONCLUSIVE
    assert result.reasons == ("resolved trial count 0 is below required 1",)


def test_release_gate_reject_keeps_hard_failure_before_uncertainty() -> None:
    report = ReliabilityReport.from_verdicts(
        [TrialVerdict.FAIL, TrialVerdict.BLOCKED]
    )
    result = ReleaseGate(
        _gate_policy(
            min_success_rate=1.0,
            max_blocked_trials=0,
            min_resolved_trials=2,
        )
    ).decide(report, critical_violations=1)

    assert result.decision is GateDecision.REJECT
    assert result.reasons == (
        "critical violations 1 exceed maximum 0",
        "success rate 0.0000 is below 1.0000",
        "blocked trials 1 exceed maximum 0",
        "resolved trial count 1 is below required 2",
    )
