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
            events=(
                EvidenceEvent(sequence=1, kind=EvidenceKind.OUTPUT, source="sut"),
            ),
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
