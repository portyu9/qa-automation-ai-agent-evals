"""Population-aware repeated-trial session wrapper."""

from __future__ import annotations

from dataclasses import dataclass

from agent_evals.adapters.base import AgentAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.runtime.population import PopulationProvenance, validate_population_provenance
from agent_evals.runtime.reset_isolation import ResetIsolationControl
from agent_evals.runtime.sampling import RandomnessControl, RandomnessStatus
from agent_evals.runtime.sampling_v2 import SessionSamplingMetadataV2
from agent_evals.runtime.session import (
    EvaluationSession,
    EvaluationSessionResult,
    IndependenceQualifiedMetrics,
    IndependenceStatus,
)


@dataclass(frozen=True, slots=True)
class PopulationQualifiedMetrics:
    """Independent-attempt metrics plus explicit target-population provenance."""

    attempts: IndependenceQualifiedMetrics
    population_schema_version: str
    population_status: str
    population_identity: str | None
    population_basis: str | None


@dataclass(frozen=True, slots=True)
class PopulationBoundSessionResult:
    """A finalized session plus population-aware statistical provenance."""

    session: EvaluationSessionResult
    sampling_metadata: SessionSamplingMetadataV2

    def validate(self) -> None:
        self.session.validate()
        self.sampling_metadata.validate_against_session(self.session)

    def independence_qualified_metrics(self) -> PopulationQualifiedMetrics:
        """Expose attempt transforms without upgrading the population claim."""
        self.validate()
        attempts = self.session.independence_qualified_metrics()
        population = self.sampling_metadata.population_provenance
        return PopulationQualifiedMetrics(
            attempts=attempts,
            population_schema_version=population.schema_version,
            population_status=population.status.value,
            population_identity=population.population_identity,
            population_basis=population.basis,
        )


class PopulationBoundEvaluationSession:
    """Require population provenance before any subject attempt executes.

    This wrapper delegates execution to :class:`EvaluationSession` and then binds its exact v1
    attempt provenance into ``agent-evals/session-sampling/v2`` together with the population
    provenance that was validated before execution. Population metadata does not alter subject
    verdicts or establish representativeness/IID behavior.
    """

    def __init__(self, *, session: EvaluationSession | None = None) -> None:
        self._session = session or EvaluationSession()

    async def run(
        self,
        adapter: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trials: int,
        population_provenance: PopulationProvenance,
        k: int = 1,
        campaign_id: str | None = None,
        independence_status: IndependenceStatus = IndependenceStatus.UNVERIFIED,
        independence_basis: str | None = None,
        reset_control: ResetIsolationControl | None = None,
        randomness_status: RandomnessStatus = RandomnessStatus.UNKNOWN,
        randomness_basis: str | None = None,
        randomness_control: RandomnessControl | None = None,
    ) -> PopulationBoundSessionResult:
        population = validate_population_provenance(population_provenance)
        session = await self._session.run(
            adapter,
            subject=subject,
            scenario=scenario,
            trials=trials,
            k=k,
            campaign_id=campaign_id,
            independence_status=independence_status,
            independence_basis=independence_basis,
            reset_control=reset_control,
            randomness_status=randomness_status,
            randomness_basis=randomness_basis,
            randomness_control=randomness_control,
        )
        result = PopulationBoundSessionResult(
            session=session,
            sampling_metadata=SessionSamplingMetadataV2.from_session(
                session,
                population_provenance=population,
            ),
        )
        result.validate()
        return result
