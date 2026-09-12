from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.adapters.base import AdapterResult
from agent_evals.assurance.report_v7 import AssuranceReportV7
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.gates.release import GateDecision, ReleasePolicy
from agent_evals.runtime.population import (
    PopulationFrame,
    PopulationProvenance,
    PopulationProvenanceError,
    PopulationStatus,
)
from agent_evals.runtime.population_session import PopulationBoundEvaluationSession
from agent_evals.runtime.sampling_v2 import SessionSamplingMetadataV2


class _Adapter:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "population-fixture"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        self.calls += 1
        return AdapterResult(final_state={"status": "ok"})


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="fixture",
        model="population-subject",
        application_revision="1",
        instructions="Return a deterministic fixture result.",
        tool_schema={},
        policy={},
        memory_policy={"retention": "trial"},
        adapter="population-fixture",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="population.bound-assurance",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Exercise population-bound statistical provenance.",
        required_outcomes={"status": "ok"},
    )


def _policy() -> ReleasePolicy:
    return ReleasePolicy(
        min_resolved_trials=1,
        min_success_rate=0.0,
        min_wilson_low=0.0,
        max_critical_violations=0,
        max_blocked_trials=0,
        max_inconclusive_trials=0,
    )


def _population(*, revision: str = "2026.09") -> PopulationProvenance:
    frame = PopulationFrame.create(
        namespace="scenario-suite",
        population_id="payments-regression",
        revision=revision,
        definition_identity="a" * 64,
    )
    return PopulationProvenance.identified(frame)


@pytest.mark.asyncio
async def test_population_must_be_valid_before_subject_execution() -> None:
    adapter = _Adapter()
    malformed = PopulationProvenance.unknown().model_copy(update={"basis": "post-hoc claim"})

    with pytest.raises(PopulationProvenanceError, match="malformed"):
        await PopulationBoundEvaluationSession().run(
            adapter,
            subject=_subject(),
            scenario=_scenario(),
            trials=1,
            population_provenance=malformed,
        )

    assert adapter.calls == 0


@pytest.mark.asyncio
async def test_population_bound_session_emits_v2_without_reinterpreting_v1() -> None:
    result = await PopulationBoundEvaluationSession().run(
        _Adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="population-v2",
        population_provenance=_population(),
    )

    assert result.session.sampling_metadata is not None
    assert result.session.sampling_metadata.schema_version == "agent-evals/session-sampling/v1"
    assert result.sampling_metadata.schema_version == "agent-evals/session-sampling/v2"
    assert result.sampling_metadata.attempt_provenance == result.session.sampling_metadata
    assert result.sampling_metadata.population_provenance.status is PopulationStatus.IDENTIFIED

    with pytest.raises(ValidationError):
        SessionSamplingMetadataV2.model_validate(
            result.session.sampling_metadata.model_dump(mode="json")
        )


@pytest.mark.asyncio
async def test_assurance_report_v7_round_trip_binds_population_and_preserves_release_authority() -> None:
    result = await PopulationBoundEvaluationSession().run(
        _Adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=2,
        campaign_id="population-report",
        population_provenance=_population(),
    )
    report = AssuranceReportV7.from_session(
        result,
        scenario=_scenario(),
        release_policy=_policy(),
    )
    loaded = AssuranceReportV7.model_validate_json(report.model_dump_json())

    assert report.schema_version == "agent-evals/assurance-report/v7"
    assert report.predecessor_report.schema_version == "agent-evals/assurance-report/v6"
    assert report.population_provenance == _population()
    assert report.gate.decision is GateDecision.ACCEPT
    assert report.gate == report.predecessor_report.gate
    assert loaded == report

    with pytest.raises(ValidationError):
        AssuranceReportV7.model_validate(report.predecessor_report.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_population_metadata_rejects_cross_campaign_replay() -> None:
    session = PopulationBoundEvaluationSession()
    first = await session.run(
        _Adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="population-first",
        population_provenance=_population(),
    )
    second = await session.run(
        _Adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="population-second",
        population_provenance=_population(),
    )

    with pytest.raises(PopulationProvenanceError, match="campaign does not match"):
        first.sampling_metadata.validate_against_session(second.session)


@pytest.mark.asyncio
async def test_cross_population_swap_invalidates_v7_root() -> None:
    result = await PopulationBoundEvaluationSession().run(
        _Adapter(),
        subject=_subject(),
        scenario=_scenario(),
        trials=1,
        campaign_id="population-swap",
        population_provenance=_population(revision="2026.09"),
    )
    report = AssuranceReportV7.from_session(
        result,
        scenario=_scenario(),
        release_policy=_policy(),
    )
    replacement = SessionSamplingMetadataV2.from_session(
        result.session,
        population_provenance=_population(revision="2026.10"),
    )
    payload = report.model_dump(mode="json")
    payload["session_sampling"] = replacement.model_dump(mode="json")

    with pytest.raises(ValidationError, match="v7 root does not match"):
        AssuranceReportV7.model_validate(payload)


def test_external_population_declaration_is_not_upgraded_to_identified() -> None:
    provenance = PopulationProvenance.externally_declared(
        "Operator declares the observed cohort to represent September production traffic."
    )

    assert provenance.status is PopulationStatus.EXTERNALLY_DECLARED
    assert provenance.population_identity is None
    assert provenance.frame is None


def test_unknown_population_is_explicit_and_carries_no_claim() -> None:
    provenance = PopulationProvenance.unknown()

    assert provenance.status is PopulationStatus.UNKNOWN
    assert provenance.population_identity is None
    assert provenance.basis is None
