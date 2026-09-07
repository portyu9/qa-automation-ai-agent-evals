from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_evals.adapters.openai_agents import _PreparedExecution
from agent_evals.adapters.openai_hitl_approval import OpenAIAgentsHITLApprovalAdapter
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind


class _ProbeHITLAdapter(OpenAIAgentsHITLApprovalAdapter):
    def __init__(self) -> None:
        super().__init__(object(), state_reader=lambda: {})
        self.start_sequences: list[int] = []

    def _normalize_items(
        self,
        items: Sequence[object],
        *,
        start_sequence: int = 0,
        tool_result_recorder: Any | None = None,
        environment_recorder: Any | None = None,
        handoff_recorder: Any | None = None,
    ) -> list[EvidenceEvent]:
        del items, tool_result_recorder, environment_recorder, handoff_recorder
        self.start_sequences.append(start_sequence)
        return [
            EvidenceEvent(
                sequence=start_sequence,
                kind=EvidenceKind.OUTPUT,
                source="probe:normalized",
                payload={"marker": "normalized"},
            )
        ]


def _prepared(*events: EvidenceEvent) -> _PreparedExecution:
    return _PreparedExecution(
        agent=object(),
        runner_input="probe",
        delivery_events=events,
    )


def test_prepared_static_evidence_is_preserved_once_before_normalized_items() -> None:
    adapter = _ProbeHITLAdapter()
    static = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.GUARDRAIL,
        source="probe:prepared",
        payload={"marker": "prepared"},
    )

    events = adapter._normalize_prepared_items(_prepared(static), ())

    assert len(events) == 2
    assert events[0] is static
    assert events[1].sequence == 1
    assert events[1].kind is EvidenceKind.OUTPUT
    assert events[1].source == "probe:normalized"
    assert events[1].payload == {"marker": "normalized"}
    assert adapter.start_sequences == [1]


def test_recorder_driven_normalization_still_starts_at_zero_without_static_evidence() -> None:
    adapter = _ProbeHITLAdapter()

    events = adapter._normalize_prepared_items(_prepared(), ())

    assert len(events) == 1
    assert events[0].sequence == 0
    assert events[0].kind is EvidenceKind.OUTPUT
    assert events[0].source == "probe:normalized"
    assert events[0].payload == {"marker": "normalized"}
    assert adapter.start_sequences == [0]
