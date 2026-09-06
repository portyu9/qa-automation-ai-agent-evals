from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

IDENTITY = "a" * 64


def test_trial_rejects_reordered_or_gapped_evidence() -> None:
    with pytest.raises(ValidationError):
        TrialEvidence(
            trial_id="t-1",
            subject_identity=IDENTITY,
            scenario_identity=IDENTITY,
            events=(EvidenceEvent(sequence=1, kind=EvidenceKind.OUTPUT, source="sut"),),
        )


def test_evidence_root_changes_when_terminal_state_changes() -> None:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.OUTPUT,
        source="sut",
        payload={"value": "ok"},
    )
    first = TrialEvidence(
        trial_id="t-1",
        subject_identity=IDENTITY,
        scenario_identity=IDENTITY,
        events=(event,),
        final_state={"status": "one"},
    )
    second = first.model_copy(update={"final_state": {"status": "two"}})
    assert first.evidence_root != second.evidence_root


def test_evidence_root_binds_subject_scenario_and_trial_identity() -> None:
    base = TrialEvidence(
        trial_id="t-1",
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        final_state={"status": "same"},
    )
    different_subject = base.model_copy(update={"subject_identity": "c" * 64})
    different_scenario = base.model_copy(update={"scenario_identity": "d" * 64})
    different_trial = base.model_copy(update={"trial_id": "t-2"})

    roots = {
        base.evidence_root,
        different_subject.evidence_root,
        different_scenario.evidence_root,
        different_trial.evidence_root,
    }
    assert len(roots) == 4


def test_event_payload_detaches_nested_adapter_owned_json() -> None:
    source = {"nested": {"items": ["before"]}}
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="adapter:test",
        payload=source,
    )
    digest = event.digest

    nested = source["nested"]
    assert isinstance(nested, dict)
    items = nested["items"]
    assert isinstance(items, list)
    items.append("after")

    assert event.payload == {"nested": {"items": ["before"]}}
    assert event.digest == digest


def test_trial_final_state_detaches_nested_adapter_owned_json() -> None:
    source = {"nested": {"items": ["before"]}}
    evidence = TrialEvidence(
        trial_id="t-detached-state",
        subject_identity=IDENTITY,
        scenario_identity=IDENTITY,
        final_state=source,
    )
    root = evidence.evidence_root

    nested = source["nested"]
    assert isinstance(nested, dict)
    items = nested["items"]
    assert isinstance(items, list)
    items.append("after")

    assert evidence.final_state == {"nested": {"items": ["before"]}}
    assert evidence.evidence_root == root


def test_trial_revalidates_and_detaches_adapter_owned_event_instance() -> None:
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="adapter:test",
        payload={"nested": {"items": ["before"]}},
    )
    evidence = TrialEvidence(
        trial_id="t-detached-event",
        subject_identity=IDENTITY,
        scenario_identity=IDENTITY,
        events=(event,),
    )
    root = evidence.evidence_root

    nested = event.payload["nested"]
    assert isinstance(nested, dict)
    items = nested["items"]
    assert isinstance(items, list)
    items.append("after")

    assert evidence.events[0] is not event
    assert evidence.events[0].payload == {"nested": {"items": ["before"]}}
    assert evidence.evidence_root == root


def test_evidence_snapshot_preserves_root_and_detaches_nested_containers() -> None:
    evidence = TrialEvidence(
        trial_id="t-snapshot",
        subject_identity=IDENTITY,
        scenario_identity=IDENTITY,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="adapter:test",
                payload={"nested": {"items": ["event"]}},
            ),
        ),
        final_state={"nested": {"items": ["state"]}},
    )
    snapshot = evidence.snapshot()
    root = snapshot.evidence_root

    original_event_nested = evidence.events[0].payload["nested"]
    assert isinstance(original_event_nested, dict)
    original_event_items = original_event_nested["items"]
    assert isinstance(original_event_items, list)
    original_event_items.append("mutated")

    original_state_nested = evidence.final_state["nested"]
    assert isinstance(original_state_nested, dict)
    original_state_items = original_state_nested["items"]
    assert isinstance(original_state_items, list)
    original_state_items.append("mutated")

    assert snapshot.events[0].payload == {"nested": {"items": ["event"]}}
    assert snapshot.final_state == {"nested": {"items": ["state"]}}
    assert snapshot.evidence_root == root
