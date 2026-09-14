"""Public trial evaluator with evaluator-owned runtime metric provenance.

The grading engine lives in ``_evaluator_core`` unchanged.  This facade validates optional
adapter metric-source assertions before subject execution and attaches a versioned provenance
sidecar after the core evaluator has finalized evidence.  ``TrialEvidence/v2`` remains historical
and unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult, AgentAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.runtime._evaluator_core import (
    EvaluatedTrial as _CoreEvaluatedTrial,
)
from agent_evals.runtime._evaluator_core import TrialRunner as _CoreTrialRunner
from agent_evals.runtime.metric_provenance import (
    MetricOrigin,
    MetricProvenanceError,
    RuntimeMetricProvenance,
    resolve_metric_provenance,
)

_REJECTED_ADAPTER_NAME = "metric-provenance-rejected"


@dataclass(frozen=True, slots=True)
class EvaluatedTrial(_CoreEvaluatedTrial):
    """Core evaluated trial plus optional evaluator-owned metric provenance."""

    metric_provenance: RuntimeMetricProvenance | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        _CoreEvaluatedTrial.__post_init__(self)
        if self.metric_provenance is not None:
            self.metric_provenance.validate_against_evidence(self.evidence)


class _RejectedMetricProvenanceAdapter:
    @property
    def name(self) -> str:
        return _REJECTED_ADAPTER_NAME

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, scenario, trial_id
        raise AdapterPreconditionError(
            code="invalid_metric_provenance",
            reason="adapter metric provenance assertion is invalid or unbounded",
        )


class TrialRunner(_CoreTrialRunner):
    """Core fail-closed evaluator with a non-authoritative metric provenance sidecar."""

    async def run(
        self,
        adapter: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> EvaluatedTrial:
        started = perf_counter()
        try:
            runtime_adapter_name, origin, assertion = resolve_metric_provenance(adapter)
            execution_adapter: AgentAdapter = adapter
        except MetricProvenanceError:
            runtime_adapter_name = _REJECTED_ADAPTER_NAME
            origin = MetricOrigin.ADAPTER_BOUNDARY
            assertion = None
            execution_adapter = _RejectedMetricProvenanceAdapter()

        evaluated = await self._run_trial(
            execution_adapter,
            subject=subject,
            scenario=scenario,
            trial_id=trial_id,
            started=started,
        )
        evaluator_elapsed_ms = max(0.0, (perf_counter() - started) * 1000.0)
        metric_provenance = RuntimeMetricProvenance.create(
            evaluated.evidence,
            runtime_adapter_name=runtime_adapter_name,
            origin=origin,
            assertion=assertion,
        )
        return EvaluatedTrial(
            evidence=evaluated.evidence,
            oracle_results=evaluated.oracle_results,
            verdict=evaluated.verdict,
            semantic_judgment=evaluated.semantic_judgment,
            evaluator_elapsed_ms=evaluator_elapsed_ms,
            metric_provenance=metric_provenance,
        )
