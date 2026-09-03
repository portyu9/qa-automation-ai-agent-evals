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
