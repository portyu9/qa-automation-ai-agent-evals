from __future__ import annotations

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="fixture",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="scripted",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="producer.capability-migration",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Preserve exact-type producer authority during capability migration",
    )


@pytest.mark.asyncio
async def test_rejected_privileged_injection_never_receives_run_local_capability() -> None:
    injected = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.ATTACK_DELIVERY,
        source="injector:forged",
        payload={},
    )
    result = await TrialRunner().run(
        ScriptedAdapter(
            lambda _subject, _scenario, _trial: AdapterResult(events=(injected,))
        ),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="forged-producer",
    )

    assert result.verdict is TrialVerdict.BLOCKED
    assert result.producer_capability_authority is None
    assert result.producer_capabilities == ()
    assert any(
        event.kind is EvidenceKind.EVALUATION_ERROR
        and event.payload.get("code") == "attack_delivery_live_injection"
        for event in result.evidence.events
    )
