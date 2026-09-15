from __future__ import annotations

import pytest

import agent_evals.runtime.preconditions as preconditions
from agent_evals.authority import validated_handoff_state_before
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    HandoffAuthorityGrant,
    ScenarioKind,
)
from agent_evals.contracts.resource import (
    ResourceIdentifier,
    ResourceScope,
    resource_identifier_payload,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.runtime.preconditions import EvaluationPreconditionError

_ROOT = "Root agent"
_CHILD = "Specialist agent"
_SUBJECT = "a" * 64


def _scope(*components: str) -> ResourceScope:
    return ResourceScope(domain="tenant", components=components)


def _handoff_authority() -> AuthorityPolicy:
    return AuthorityPolicy(
        allowed_tools=frozenset({"read"}),
        allowed_resource_scopes=(_scope("7"),),
        max_tool_calls=5,
        max_handoffs=2,
        root_agent=_ROOT,
        handoff_grants=(
            HandoffAuthorityGrant(
                source_agent=_ROOT,
                target_agent=_CHILD,
                allowed_tools=frozenset({"read"}),
                allowed_resource_scopes=(_scope("7", "orders"),),
                max_tool_calls=3,
                max_handoffs=1,
            ),
        ),
    )


def _scenario(authority: AuthorityPolicy | None = None) -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="mutation.precondition-contracts",
        revision="1",
        kind=ScenarioKind.SECURITY,
        objective="Preserve fail-closed pregrading traversal and provenance semantics.",
        authority=authority or AuthorityPolicy(),
    )


def _event(sequence: int, kind: EvidenceKind, **payload: object) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=sequence,
        kind=kind,
        source="test",
        payload=payload,
    )


def _evidence(
    scenario: EvaluationScenario,
    *events: EvidenceEvent,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id="mutation-preconditions",
        subject_identity=_SUBJECT,
        scenario_identity=scenario.identity,
        events=events,
    )


def _valid_resource() -> dict[str, object]:
    return resource_identifier_payload(
        ResourceIdentifier(
            domain="tenant",
            components=("7", "orders", "42"),
        )
    )


def test_pregrading_closure_passes_exact_evidence_to_composed_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _scenario()
    evidence = _evidence(scenario)
    observed: list[tuple[EvaluationScenario, TrialEvidence | None]] = []

    def capture(
        scenario_arg: EvaluationScenario,
        evidence_arg: TrialEvidence | None,
    ) -> None:
        observed.append((scenario_arg, evidence_arg))

    monkeypatch.setattr(preconditions, "_verify_composed_handoff_provenance", capture)

    preconditions.verify_pregrading_closure(scenario, evidence)

    assert observed == [(scenario, evidence)]


def test_typed_resource_traversal_skips_unrelated_events_before_required_identity() -> None:
    scenario = _scenario(
        AuthorityPolicy(
            allowed_tools=frozenset({"read"}),
            allowed_resource_scopes=(_scope("7"),),
        )
    )
    evidence = _evidence(
        scenario,
        _event(0, EvidenceKind.TOOL_RESULT, output="unrelated"),
        _event(1, EvidenceKind.TOOL_REQUEST, tool="read", call_id="missing-resource"),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions._verify_typed_resource_evidence(scenario, evidence)

    assert captured.value.source == "evaluator:resource-identity"
    assert captured.value.code == "resource_identity_unverified"
    assert captured.value.reason == (
        "tool_request evidence lacks the resource identity required by the active typed resource scope"
    )


def test_typed_resource_traversal_continues_after_one_valid_identity() -> None:
    scenario = _scenario(
        AuthorityPolicy(
            allowed_tools=frozenset({"read"}),
            allowed_resource_scopes=(_scope("7"),),
        )
    )
    evidence = _evidence(
        scenario,
        _event(
            0,
            EvidenceKind.TOOL_REQUEST,
            tool="read",
            call_id="valid-resource",
            resource=_valid_resource(),
        ),
        _event(1, EvidenceKind.TOOL_REQUEST, tool="read", call_id="missing-resource"),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions._verify_typed_resource_evidence(scenario, evidence)

    assert captured.value.reason == (
        "tool_request evidence lacks the resource identity required by the active typed resource scope"
    )


def test_typed_resource_malformed_identity_has_exact_structured_error() -> None:
    scenario = _scenario()
    evidence = _evidence(
        scenario,
        _event(
            0,
            EvidenceKind.TOOL_REQUEST,
            tool="read",
            call_id="malformed-resource",
            resource="tenant:7",
        ),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions._verify_typed_resource_evidence(scenario, evidence)

    assert captured.value.source == "evaluator:resource-identity"
    assert captured.value.code == "resource_identity_unverified"
    assert captured.value.reason == (
        "tool_request evidence contains a malformed or non-canonical typed resource identity"
    )


def test_typed_resource_missing_identity_uses_exact_active_handoff_state() -> None:
    authority = _handoff_authority()
    scenario = _scenario(authority)
    events = (
        _event(
            0,
            EvidenceKind.HANDOFF,
            source_agent=_ROOT,
            target_agent=_CHILD,
        ),
        _event(
            1,
            EvidenceKind.TOOL_REQUEST,
            agent=_CHILD,
            tool="read",
            call_id="missing-resource",
        ),
    )
    evidence = _evidence(scenario, *events)

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions._verify_typed_resource_evidence(scenario, evidence)

    assert captured.value.source == "evaluator:resource-identity"
    assert captured.value.code == "resource_identity_unverified"
    assert captured.value.reason == (
        "tool_request evidence lacks the resource identity required by the active typed resource scope"
    )


def test_handoff_state_replay_skips_unrelated_events_before_transition() -> None:
    authority = _handoff_authority()
    events = (
        _event(0, EvidenceKind.TOOL_RESULT, output="unrelated"),
        _event(
            1,
            EvidenceKind.HANDOFF,
            source_agent=_ROOT,
            target_agent=_CHILD,
        ),
    )

    state = validated_handoff_state_before(authority, events, 2)

    assert state.active_agent == _CHILD
    assert state.epoch == 1
    assert state.transitions == ((_ROOT, _CHILD),)


def test_composed_provenance_missing_agent_has_exact_structured_error() -> None:
    scenario = _scenario(_handoff_authority())
    evidence = _evidence(
        scenario,
        _event(0, EvidenceKind.PROTOCOL_DELIVERY, bridge="already-verified"),
        _event(1, EvidenceKind.TOOL_REQUEST, tool="read", call_id="missing-agent"),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions._verify_composed_handoff_provenance(scenario, evidence)

    assert captured.value.source == "evaluator:handoff-provenance"
    assert captured.value.code == "handoff_provenance_unverified"
    assert captured.value.reason == (
        "specialized OpenAI evidence under delegated handoff authority lacks a stable "
        "generating-agent identity for tool_request"
    )


def test_composed_provenance_one_missing_handoff_identity_is_fail_closed() -> None:
    scenario = _scenario(_handoff_authority())
    evidence = _evidence(
        scenario,
        _event(0, EvidenceKind.PROTOCOL_DELIVERY, bridge="already-verified"),
        _event(
            1,
            EvidenceKind.HANDOFF,
            source_agent="",
            target_agent=_CHILD,
        ),
    )

    with pytest.raises(EvaluationPreconditionError) as captured:
        preconditions._verify_composed_handoff_provenance(scenario, evidence)

    assert captured.value.source == "evaluator:handoff-provenance"
    assert captured.value.code == "handoff_provenance_unverified"
    assert captured.value.reason == (
        "specialized OpenAI evidence under delegated handoff authority contains a handoff "
        "without stable source and target agent identities"
    )
