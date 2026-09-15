from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.metric_provenance import (
    MetricTelemetryAuthority,
    MetricTelemetrySource,
    PricingProvenanceStatus,
    RuntimeMetricProvenance,
    RuntimeMetricSourceAssertion,
    classify_metric_source,
)
from agent_evals.runtime.session import EvaluationSession


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="metric-test",
        model="deterministic",
        application_revision="rev-1",
        instructions="",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="metric-test",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="runtime.metric-provenance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Record runtime telemetry without promoting it to grading authority.",
    )


def _evidence(*, input_tokens: int = 7, output_tokens: int = 3, cost: float = 0.25) -> TrialEvidence:
    subject = _subject()
    scenario = _scenario()
    return TrialEvidence(
        trial_id="metric-trial",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=cost,
    )


def test_metric_provenance_binds_exact_v2_values_without_changing_v2_schema() -> None:
    evidence = _evidence()
    assertion = RuntimeMetricSourceAssertion(
        source_name="fixture-usage-counter",
        source_version="2",
        pricing_source="fixture-price-sheet",
        pricing_version="2026-09-01",
    )

    provenance = RuntimeMetricProvenance.create(
        evidence=evidence,
        runtime_adapter_name="metric-fixture",
        source=MetricTelemetrySource.ADAPTER_ASSERTED,
        source_assertion=assertion,
    )

    provenance.validate_against_evidence(evidence)
    assert provenance.authority is MetricTelemetryAuthority.UNVERIFIED
    assert provenance.pricing_status is PricingProvenanceStatus.ADAPTER_ASSERTED
    assert provenance.evidence_root == evidence.evidence_root
    assert "metric_provenance" not in evidence.model_dump(mode="json")

    changed = TrialEvidence(
        **{
            **evidence.model_dump(mode="python"),
            "input_tokens": evidence.input_tokens + 1,
        }
    )
    with pytest.raises(ValueError, match="evidence root does not match"):
        provenance.validate_against_evidence(changed)


def test_metric_provenance_rejects_source_or_pricing_mutation_under_stale_root() -> None:
    provenance = RuntimeMetricProvenance.create(
        evidence=_evidence(),
        runtime_adapter_name="metric-fixture",
        source=MetricTelemetrySource.ADAPTER_ASSERTED,
        source_assertion=RuntimeMetricSourceAssertion(
            source_name="fixture-usage-counter",
            source_version="2",
            pricing_source="fixture-price-sheet",
            pricing_version="2026-09-01",
        ),
    )
    material = provenance.model_dump(mode="python")
    assertion = dict(material["source_assertion"])
    assertion["pricing_version"] = "mutated"
    material["source_assertion"] = assertion

    with pytest.raises(ValidationError, match="provenance root"):
        RuntimeMetricProvenance.model_validate(material)


@pytest.mark.asyncio
async def test_generic_adapter_gets_explicit_unknown_unverified_metric_provenance() -> None:
    adapter = ScriptedAdapter(
        lambda _subject, _scenario, _trial: AdapterResult(
            input_tokens=11,
            output_tokens=5,
            estimated_cost_usd=0.125,
        ),
        name="manual-fixture",
    )

    evaluated = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trial_id="manual-metrics",
    )

    assert evaluated.verdict is TrialVerdict.PASS
    assert evaluated.metric_provenance is not None
    provenance = evaluated.metric_provenance
    assert provenance.authority is MetricTelemetryAuthority.UNVERIFIED
    assert provenance.source is MetricTelemetrySource.UNKNOWN
    assert provenance.source_assertion is None
    assert provenance.pricing_status is PricingProvenanceStatus.UNKNOWN
    provenance.validate_against_evidence(evaluated.evidence)


class _AssertedMetricAdapter(ScriptedAdapter):
    @property
    def runtime_metric_provenance_assertion(self) -> RuntimeMetricSourceAssertion:
        return RuntimeMetricSourceAssertion(
            source_name="fixture-provider-usage",
            source_version="v3",
            pricing_source="fixture-pricing-catalog",
            pricing_version="2026-09-14",
        )


@pytest.mark.asyncio
async def test_adapter_assertion_is_retained_but_cannot_upgrade_metric_authority() -> None:
    adapter = _AssertedMetricAdapter(
        lambda _subject, _scenario, _trial: AdapterResult(
            input_tokens=17,
            output_tokens=9,
            estimated_cost_usd=0.5,
        ),
        name="asserted-fixture",
    )

    evaluated = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trial_id="asserted-metrics",
    )

    assert evaluated.metric_provenance is not None
    provenance = evaluated.metric_provenance
    assert provenance.authority is MetricTelemetryAuthority.UNVERIFIED
    assert provenance.source is MetricTelemetrySource.ADAPTER_ASSERTED
    assert provenance.pricing_status is PricingProvenanceStatus.ADAPTER_ASSERTED
    assert provenance.source_assertion is not None
    assert provenance.source_assertion.pricing_version == "2026-09-14"


class _MalformedMetricAssertionAdapter:
    def __init__(self) -> None:
        self.executed = False

    @property
    def name(self) -> str:
        return "malformed-metric-assertion"

    @property
    def runtime_metric_provenance_assertion(self) -> object:
        return {
            "source_name": " fixture ",
            "pricing_source": "catalog-without-version",
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
        return AdapterResult(input_tokens=1)


@pytest.mark.asyncio
async def test_malformed_metric_assertion_blocks_before_subject_execution() -> None:
    adapter = _MalformedMetricAssertionAdapter()

    evaluated = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trial_id="malformed-metric-assertion",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert adapter.executed is False
    assert evaluated.metric_provenance is None
    assert len(evaluated.evidence.events) == 1
    event = evaluated.evidence.events[0]
    assert event.kind is EvidenceKind.EVALUATION_ERROR
    assert event.payload == {
        "code": "invalid_metric_provenance_assertion",
        "reason": "adapter runtime metric provenance assertion failed validation",
    }


class _ExplodingMetricAssertionAdapter(_MalformedMetricAssertionAdapter):
    @property
    def runtime_metric_provenance_assertion(self) -> object:
        raise RuntimeError("provider metadata lookup should not escape the evaluator boundary")


@pytest.mark.asyncio
async def test_metric_assertion_getter_exception_blocks_before_subject_execution() -> None:
    adapter = _ExplodingMetricAssertionAdapter()

    evaluated = await TrialRunner().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trial_id="exploding-metric-assertion",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert adapter.executed is False
    assert evaluated.evidence.events[0].payload["code"] == "invalid_metric_provenance_assertion"


@pytest.mark.asyncio
async def test_exact_evidence_replay_never_upgrades_historical_metric_provenance() -> None:
    subject = _subject()
    scenario = _scenario()
    evidence = TrialEvidence(
        trial_id="replayed-metrics",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        input_tokens=23,
        output_tokens=8,
        estimated_cost_usd=0.75,
    )

    evaluated = await TrialRunner().run(
        EvidenceReplayAdapter(evidence),
        subject=subject,
        scenario=scenario,
        trial_id=evidence.trial_id,
    )

    assert evaluated.verdict is TrialVerdict.PASS
    assert evaluated.metric_provenance is not None
    provenance = evaluated.metric_provenance
    assert provenance.authority is MetricTelemetryAuthority.UNVERIFIED
    assert provenance.source is MetricTelemetrySource.HISTORICAL_EVIDENCE_REPLAY
    assert provenance.source_assertion is None
    assert provenance.pricing_status is PricingProvenanceStatus.UNKNOWN


def test_exact_openai_adapter_classifies_nonzero_sdk_usage_without_pricing_claim() -> None:
    adapter = OpenAIAgentsAdapter(object(), state_reader=lambda: {})
    source, assertion = classify_metric_source(adapter, None)
    provenance = RuntimeMetricProvenance.create(
        evidence=_evidence(input_tokens=31, output_tokens=12, cost=0.0),
        runtime_adapter_name=adapter.name,
        source=source,
        source_assertion=assertion,
    )

    assert provenance.authority is MetricTelemetryAuthority.UNVERIFIED
    assert provenance.source is MetricTelemetrySource.OPENAI_AGENTS_SDK_USAGE
    assert provenance.source_assertion is not None
    assert provenance.source_assertion.source_name == (
        "openai-agents-sdk:result.context_wrapper.usage"
    )
    assert provenance.pricing_status is PricingProvenanceStatus.UNKNOWN


def test_openai_path_downgrades_to_unknown_when_no_token_telemetry_was_retained() -> None:
    adapter = OpenAIAgentsAdapter(object(), state_reader=lambda: {})
    source, assertion = classify_metric_source(adapter, None)
    provenance = RuntimeMetricProvenance.create(
        evidence=_evidence(input_tokens=0, output_tokens=0, cost=0.0),
        runtime_adapter_name=adapter.name,
        source=source,
        source_assertion=assertion,
    )

    assert provenance.source is MetricTelemetrySource.UNKNOWN
    assert provenance.source_assertion is None
    assert provenance.pricing_status is PricingProvenanceStatus.UNKNOWN


@pytest.mark.asyncio
async def test_session_retains_each_trial_metric_provenance_without_using_it_as_gate_authority() -> None:
    adapter = ScriptedAdapter(
        lambda _subject, _scenario, _trial: AdapterResult(input_tokens=2, output_tokens=1),
        name="session-metric-fixture",
    )

    session = await EvaluationSession().run(
        adapter,
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="metric-provenance-session",
    )

    assert all(trial.metric_provenance is not None for trial in session.trials)
    assert session.reliability.total == 2
    assert session.reliability.passed == 2
    assert all(
        trial.metric_provenance is not None
        and trial.metric_provenance.authority is MetricTelemetryAuthority.UNVERIFIED
        for trial in session.trials
    )


def test_evaluated_trial_rejects_metric_provenance_bound_to_different_evidence() -> None:
    evidence = _evidence()
    provenance = RuntimeMetricProvenance.create(
        evidence=evidence,
        runtime_adapter_name="fixture",
        source=MetricTelemetrySource.UNKNOWN,
    )
    changed = TrialEvidence(
        **{
            **evidence.model_dump(mode="python"),
            "output_tokens": evidence.output_tokens + 1,
        }
    )

    with pytest.raises(ValueError, match="evidence root does not match"):
        EvaluatedTrial(
            evidence=changed,
            oracle_results=(),
            verdict=TrialVerdict.PASS,
            metric_provenance=provenance,
        )
