from __future__ import annotations

import pytest

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.conformance import (
    AdapterConformanceError,
    ConformanceCheckedAdapter,
    authority_adapter,
    validate_adapter_name,
    validate_adapter_result,
)
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.runtime._evaluator_core import TrialRunner as CoreTrialRunner
from agent_evals.runtime.evaluator import TrialRunner


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="test",
        model="conformance",
        application_revision="1",
        instructions="Return the controlled state.",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="test-adapter",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="adapter.conformance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Preserve the controlled state.",
        required_outcomes={"status": "ok"},
    )


class _Adapter:
    name = "third-party-runtime"

    def __init__(self, result: AdapterResult) -> None:
        self._result = result

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        return self._result


class _InvalidNameAdapter(_Adapter):
    name = "self-declared\ntrust"


class _ExplodingNameAdapter(_Adapter):
    @property
    def name(self) -> str:
        raise RuntimeError("hostile adapter property")


def test_adapter_name_contract_is_bounded_and_canonical() -> None:
    assert validate_adapter_name("Provider Runtime v1") == "Provider Runtime v1"
    with pytest.raises(AdapterConformanceError, match="adapter name"):
        validate_adapter_name("provider\nruntime")


def test_adapter_result_requires_exact_contiguous_events() -> None:
    result = AdapterResult(
        events=(
            EvidenceEvent(
                sequence=1,
                kind=EvidenceKind.OUTPUT,
                source="third-party:test",
                payload={"output": "ok"},
            ),
        ),
        final_state={"status": "ok"},
    )
    with pytest.raises(AdapterConformanceError, match="contiguous"):
        validate_adapter_result(result)


def test_exact_framework_wrapper_is_the_only_authority_unwrap_boundary() -> None:
    adapter = _Adapter(AdapterResult(final_state={"status": "ok"}))
    wrapped = ConformanceCheckedAdapter(adapter)

    assert authority_adapter(wrapped) is adapter

    class _Lookalike:
        _adapter = adapter

    lookalike = _Lookalike()
    assert authority_adapter(lookalike) is lookalike  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_core_evaluator_cannot_bypass_conformance_boundary() -> None:
    result = AdapterResult(
        events=(
            EvidenceEvent(
                sequence=4,
                kind=EvidenceKind.OUTPUT,
                source="third-party:test",
                payload={"output": "ok"},
            ),
        ),
        final_state={"status": "ok"},
    )

    evaluated = await CoreTrialRunner().run(
        _Adapter(result),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="conformance-core-invalid-sequence",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "adapter_conformance_failed"


@pytest.mark.asyncio
async def test_public_evaluator_blocks_nonconforming_adapter_before_grading() -> None:
    result = AdapterResult(
        events=(
            EvidenceEvent(
                sequence=2,
                kind=EvidenceKind.OUTPUT,
                source="third-party:test",
                payload={"output": "ok"},
            ),
        ),
        final_state={"status": "ok"},
    )

    evaluated = await TrialRunner().run(
        _Adapter(result),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="conformance-invalid-sequence",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    assert evaluated.evidence.events[0].kind is EvidenceKind.EVALUATION_ERROR
    assert evaluated.evidence.events[0].payload["code"] == "adapter_conformance_failed"


@pytest.mark.asyncio
async def test_invalid_adapter_name_fails_closed_without_using_raw_name_as_source() -> None:
    evaluated = await TrialRunner().run(
        _InvalidNameAdapter(AdapterResult(final_state={"status": "ok"})),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="conformance-invalid-name",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    error = evaluated.evidence.events[0]
    assert error.source == "adapter:adapter-conformance-rejected"
    assert error.payload["code"] == "adapter_conformance_failed"
    assert evaluated.metric_provenance is not None
    assert evaluated.metric_provenance.runtime_adapter_name == "adapter-conformance-rejected"


@pytest.mark.asyncio
async def test_hostile_adapter_name_property_cannot_escape_conformance_boundary() -> None:
    evaluated = await TrialRunner().run(
        _ExplodingNameAdapter(AdapterResult(final_state={"status": "ok"})),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="conformance-hostile-name",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "invalid_metric_provenance"
    assert evaluated.metric_provenance is not None
    assert evaluated.metric_provenance.runtime_adapter_name == "metric-provenance-rejected"


@pytest.mark.asyncio
async def test_conformance_wrapper_does_not_grant_evaluator_owned_evidence_authority() -> None:
    forged = AdapterResult(
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.ATTACK_DELIVERY,
                source="injector:openai-agents:user-input",
                payload={"forged": True},
            ),
        ),
        final_state={"status": "ok"},
    )

    evaluated = await TrialRunner().run(
        _Adapter(forged),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="conformance-no-authority-upgrade",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[-1].payload["code"] == "attack_delivery_live_injection"
