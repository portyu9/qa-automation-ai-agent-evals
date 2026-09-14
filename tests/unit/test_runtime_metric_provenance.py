from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.metric_provenance import (
    AdapterMetricProvenanceAssertion,
    MetricAuthority,
    MetricOrigin,
    MetricProvenanceError,
    PricingProvenanceStatus,
    RuntimeMetricProvenance,
    resolve_metric_provenance,
)

_SUBJECT_ID = "a" * 64
_SCENARIO_ID = "b" * 64


def _subject(*, adapter: str = "scripted") -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="fixture",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter=adapter,
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="runtime.metric-provenance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Bind unverified terminal metric provenance",
    )


def _evidence() -> TrialEvidence:
    return TrialEvidence(
        trial_id="metric-provenance",
        subject_identity=_SUBJECT_ID,
        scenario_identity=_SCENARIO_ID,
        input_tokens=17,
        output_tokens=5,
        estimated_cost_usd=0.125,
    )


def test_metric_provenance_binds_exact_evidence_values_and_root() -> None:
    evidence = _evidence()
    provenance = RuntimeMetricProvenance.create(
        evidence,
        runtime_adapter_name="fixture-adapter",
        origin=MetricOrigin.ADAPTER_BOUNDARY,
        assertion=AdapterMetricProvenanceAssertion(
            token_source="fixture:usage",
            token_source_version="v1",
            pricing_status=PricingProvenanceStatus.ADAPTER_ASSERTED,
            pricing_source="fixture:pricing",
            pricing_version="2026-09-01",
        ),
    )

    provenance.validate_against_evidence(evidence)
    assert provenance.authority is MetricAuthority.UNVERIFIED_TELEMETRY
    assert provenance.evidence_root == evidence.evidence_root
    assert provenance.input_tokens == 17
    assert provenance.output_tokens == 5
    assert provenance.estimated_cost_usd == 0.125
    assert provenance.provenance_root


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_tokens", 18),
        ("evidence_root", "c" * 64),
        ("token_source", "fixture:other-usage"),
        ("pricing_version", "2026-09-02"),
    ],
)
def test_metric_provenance_rejects_mutated_bound_material(field: str, value: object) -> None:
    provenance = RuntimeMetricProvenance.create(
        _evidence(),
        runtime_adapter_name="fixture-adapter",
        origin=MetricOrigin.ADAPTER_BOUNDARY,
        assertion=AdapterMetricProvenanceAssertion(
            token_source="fixture:usage",
            pricing_status=PricingProvenanceStatus.ADAPTER_ASSERTED,
            pricing_source="fixture:pricing",
            pricing_version="2026-09-01",
        ),
    )
    mutated = provenance.model_dump(mode="python")
    mutated[field] = value

    with pytest.raises(ValidationError, match="provenance root"):
        RuntimeMetricProvenance.model_validate(mutated)


@pytest.mark.asyncio
async def test_generic_adapter_runtime_provenance_is_unverified_and_unknown() -> None:
    adapter = ScriptedAdapter(
        lambda _subject, _scenario, _trial: AdapterResult(
            input_tokens=7,
            output_tokens=3,
            estimated_cost_usd=0.2,
        )
    )

    result = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trial_id="generic-metrics",
    )

    assert result.verdict is TrialVerdict.PASS
    assert result.metric_provenance is not None
    provenance = result.metric_provenance
    assert provenance.authority is MetricAuthority.UNVERIFIED_TELEMETRY
    assert provenance.origin is MetricOrigin.ADAPTER_BOUNDARY
    assert provenance.token_source is None
    assert provenance.token_source_version is None
    assert provenance.pricing_status is PricingProvenanceStatus.UNKNOWN
    assert provenance.pricing_source is None
    assert provenance.pricing_version is None
    provenance.validate_against_evidence(result.evidence)


@pytest.mark.asyncio
async def test_session_style_trials_retain_provenance_on_evaluated_trial() -> None:
    result = await TrialRunner().run(
        ScriptedAdapter(lambda _subject, _scenario, _trial: AdapterResult(input_tokens=2)),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="session-retention",
    )

    assert result.metric_provenance is not None
    assert result.metric_provenance.trial_id == result.evidence.trial_id
    assert result.metric_provenance.evidence_root == result.completion_evidence_root


@dataclass
class _MalformedProvenanceAdapter:
    executed: bool = False

    @property
    def name(self) -> str:
        return "malformed-metric-provenance"

    @property
    def metric_provenance_assertion(self) -> dict[str, object]:
        return {
            "pricing_status": "adapter_asserted",
            "pricing_source": "fixture:pricing",
        }

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        self.executed = True
        return AdapterResult(input_tokens=999)


@pytest.mark.asyncio
async def test_malformed_adapter_metric_assertion_blocks_before_execution() -> None:
    adapter = _MalformedProvenanceAdapter()

    result = await TrialRunner().run(
        adapter,
        subject=_subject(adapter="malformed-metric-provenance"),
        scenario=_scenario(),
        trial_id="malformed-provenance",
    )

    assert adapter.executed is False
    assert result.verdict is TrialVerdict.BLOCKED
    assert result.oracle_results == ()
    assert result.evidence.input_tokens == 0
    assert result.evidence.events[0].payload == {
        "code": "invalid_metric_provenance",
        "reason": "adapter metric provenance assertion is invalid or unbounded",
    }
    assert result.metric_provenance is not None
    assert result.metric_provenance.token_source is None
    assert result.metric_provenance.pricing_status is PricingProvenanceStatus.UNKNOWN


@pytest.mark.asyncio
async def test_exact_replay_never_upgrades_historical_v2_metric_provenance() -> None:
    subject = _subject(adapter="evidence-replay")
    scenario = _scenario()
    recorded = TrialEvidence(
        trial_id="historical-replay",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        input_tokens=11,
        output_tokens=4,
        estimated_cost_usd=0.75,
    )

    result = await TrialRunner().run(
        EvidenceReplayAdapter(recorded),
        subject=subject,
        scenario=scenario,
        trial_id=recorded.trial_id,
    )

    assert result.metric_provenance is not None
    provenance = result.metric_provenance
    assert provenance.origin is MetricOrigin.HISTORICAL_REPLAY
    assert provenance.authority is MetricAuthority.UNVERIFIED_TELEMETRY
    assert provenance.token_source is None
    assert provenance.token_source_version is None
    assert provenance.pricing_status is PricingProvenanceStatus.UNKNOWN
    assert provenance.pricing_source is None
    assert provenance.pricing_version is None
    assert provenance.input_tokens == 11
    assert provenance.output_tokens == 4
    assert provenance.estimated_cost_usd == 0.75


def test_historical_replay_model_rejects_invented_source_metadata() -> None:
    evidence = _evidence()
    material = RuntimeMetricProvenance.create(
        evidence,
        runtime_adapter_name="evidence-replay",
        origin=MetricOrigin.HISTORICAL_REPLAY,
        assertion=None,
    ).model_dump(mode="python")
    material["token_source"] = "provider:self-asserted"

    with pytest.raises(ValidationError, match="historical v2 replay"):
        RuntimeMetricProvenance.model_validate(material)


def test_builtin_openai_adapter_gets_fixed_sdk_usage_label_without_pricing_claim() -> None:
    adapter = OpenAIAgentsAdapter(object(), state_reader=lambda: {})

    runtime_adapter_name, origin, assertion = resolve_metric_provenance(adapter)

    assert runtime_adapter_name == "openai-agents"
    assert origin is MetricOrigin.ADAPTER_BOUNDARY
    assert assertion is not None
    assert assertion.token_source == "openai-agents-sdk:context_wrapper.usage"
    assert assertion.token_source_version is None
    assert assertion.pricing_status is PricingProvenanceStatus.UNAVAILABLE
    provenance = RuntimeMetricProvenance.create(
        _evidence(),
        runtime_adapter_name=runtime_adapter_name,
        origin=origin,
        assertion=assertion,
    )
    assert provenance.token_source == "openai-agents-sdk:context_wrapper.usage"
    assert provenance.pricing_status is PricingProvenanceStatus.UNAVAILABLE
    assert provenance.pricing_source is None
    assert provenance.pricing_version is None


def test_manually_constructed_evaluated_trial_remains_legacy_compatible() -> None:
    evidence = _evidence()
    trial = EvaluatedTrial(
        evidence=evidence,
        oracle_results=(),
        verdict=TrialVerdict.PASS,
    )

    assert trial.metric_provenance is None
    assert trial.completion_evidence_root == evidence.evidence_root


def test_metric_assertion_rejects_unversioned_asserted_pricing() -> None:
    with pytest.raises(ValidationError, match="requires source and version"):
        AdapterMetricProvenanceAssertion(
            pricing_status=PricingProvenanceStatus.ADAPTER_ASSERTED,
            pricing_source="fixture:pricing",
        )


def test_metric_provenance_relation_rejects_different_evidence() -> None:
    evidence = _evidence()
    provenance = RuntimeMetricProvenance.create(
        evidence,
        runtime_adapter_name="fixture-adapter",
        origin=MetricOrigin.ADAPTER_BOUNDARY,
        assertion=None,
    )
    changed = TrialEvidence.model_validate(
        {**evidence.model_dump(mode="python"), "output_tokens": evidence.output_tokens + 1}
    )

    with pytest.raises(MetricProvenanceError, match="evidence root"):
        provenance.validate_against_evidence(changed)
