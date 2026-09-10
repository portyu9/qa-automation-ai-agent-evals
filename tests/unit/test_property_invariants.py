from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from agent_evals.contracts.models import SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

_SUBJECT = "a" * 64
_SCENARIO = "b" * 64
_OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)

_JSON_SCALAR = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**63), max_value=2**63 - 1)
    | st.floats(allow_nan=False, allow_infinity=False, width=32)
    | st.text(max_size=20)
)
_JSON_VALUE = st.recursive(
    _JSON_SCALAR,
    lambda children: st.lists(children, max_size=4)
    | st.dictionaries(st.text(max_size=12), children, max_size=4),
    max_leaves=20,
)
_JSON_MAPPING = st.dictionaries(st.text(max_size=12), _JSON_VALUE, max_size=8)


def _reverse_mapping_order(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _reverse_mapping_order(child)
            for key, child in reversed(list(value.items()))
        }
    if isinstance(value, list):
        return [_reverse_mapping_order(child) for child in value]
    return value


@settings(max_examples=75, deadline=None)
@given(material=_JSON_MAPPING)
def test_subject_identity_is_invariant_to_mapping_insertion_order(material: dict[str, Any]) -> None:
    reversed_material = _reverse_mapping_order(material)

    first = SubjectFingerprint.from_material(
        provider="property-provider",
        model="property-model",
        application_revision="property-rev",
        instructions="fixed instructions",
        tool_schema=material,
        policy={"policy": material},
        memory_policy={"memory": material},
        adapter="property-adapter",
        adapter_version="1",
    )
    second = SubjectFingerprint.from_material(
        provider="property-provider",
        model="property-model",
        application_revision="property-rev",
        instructions="fixed instructions",
        tool_schema=reversed_material,
        policy={"policy": reversed_material},
        memory_policy={"memory": reversed_material},
        adapter="property-adapter",
        adapter_version="1",
    )

    assert first.identity == second.identity
    assert first.tool_schema_sha256 == second.tool_schema_sha256
    assert first.policy_sha256 == second.policy_sha256
    assert first.memory_policy_sha256 == second.memory_policy_sha256


@settings(max_examples=75, deadline=None)
@given(payload=_JSON_MAPPING)
def test_event_digest_is_invariant_to_payload_mapping_order(payload: dict[str, Any]) -> None:
    reversed_payload = _reverse_mapping_order(payload)

    first = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="property:test",
        payload=payload,
        observed_at=_OBSERVED_AT,
    )
    second = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="property:test",
        payload=reversed_payload,
        observed_at=_OBSERVED_AT,
    )

    assert first.digest == second.digest


@settings(max_examples=75, deadline=None)
@given(final_state=_JSON_MAPPING)
def test_evidence_root_is_invariant_to_terminal_mapping_order(
    final_state: dict[str, Any],
) -> None:
    reversed_state = _reverse_mapping_order(final_state)

    first = TrialEvidence(
        trial_id="property-trial",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        final_state=final_state,
    )
    second = TrialEvidence(
        trial_id="property-trial",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        final_state=reversed_state,
    )

    assert first.evidence_root == second.evidence_root


@settings(max_examples=75, deadline=None)
@given(final_state=_JSON_MAPPING, suffix=st.text(min_size=1, max_size=24))
def test_evidence_root_binds_trial_identity(final_state: dict[str, Any], suffix: str) -> None:
    first = TrialEvidence(
        trial_id=f"property-a:{suffix}",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        final_state=final_state,
    )
    second = TrialEvidence(
        trial_id=f"property-b:{suffix}",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        final_state=final_state,
    )

    assert first.evidence_root != second.evidence_root
