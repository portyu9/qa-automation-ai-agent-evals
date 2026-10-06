"""Public trial evaluator with evaluator-owned runtime metric provenance.

The grading engine lives in ``_evaluator_core``. This facade validates optional adapter
metric-source assertions before subject execution and attaches a versioned provenance sidecar after
the core evaluator has finalized evidence. The core performs evaluator-owned normalized-result
conformance validation without replacing the original adapter identity. ``TrialEvidence/v2``
remains historical and unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult, AgentAdapter
from agent_evals.adapters.replay import EvidenceReplayAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialEvidence
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
from agent_evals.runtime.timing_provenance import EvaluatorTimingProvenance
from agent_evals.verification import (
    PrivilegedProducerRole,
    ProducerCapability,
    ProducerCapabilityAuthority,
)

_REJECTED_ADAPTER_NAME = "metric-provenance-rejected"


@dataclass(frozen=True, slots=True)
class EvaluatedTrial(_CoreEvaluatedTrial):
    """Core evaluated trial plus optional evaluator-owned metric provenance."""

    metric_provenance: RuntimeMetricProvenance | None = field(default=None, kw_only=True)
    timing_provenance: EvaluatorTimingProvenance | None = field(default=None, kw_only=True)
    producer_capability_authority: ProducerCapabilityAuthority | None = field(
        default=None,
        kw_only=True,
        repr=False,
        compare=False,
    )
    producer_capabilities: tuple[ProducerCapability, ...] = field(
        default=(),
        kw_only=True,
        compare=False,
    )

    def __post_init__(self) -> None:
        _CoreEvaluatedTrial.__post_init__(self)
        if self.metric_provenance is not None:
            self.metric_provenance.validate_against_evidence(self.evidence)
        if self.timing_provenance is not None:
            self.timing_provenance.validate_against_evidence(self.evidence)
            if self.evaluator_elapsed_ms != self.timing_provenance.elapsed_ms:
                raise ValueError(
                    "evaluator timing provenance elapsed_ms does not match finalized trial timing"
                )
        if self.producer_capabilities:
            authority = self.producer_capability_authority
            if authority is None:
                raise ValueError("producer capabilities require their run-local issuing authority")
            for capability in self.producer_capabilities:
                authority.require(
                    capability,
                    role=capability.role,
                    producer_id=capability.producer_id,
                )


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
        timing_provenance = EvaluatorTimingProvenance.create(
            evaluated.evidence,
            elapsed_ms=evaluator_elapsed_ms,
        )
        producer_authority, producer_capabilities = _issue_verified_producer_capabilities(
            execution_adapter,
            evaluated.evidence,
        )
        return EvaluatedTrial(
            evidence=evaluated.evidence,
            oracle_results=evaluated.oracle_results,
            verdict=evaluated.verdict,
            semantic_judgment=evaluated.semantic_judgment,
            evaluator_elapsed_ms=evaluator_elapsed_ms,
            metric_provenance=metric_provenance,
            timing_provenance=timing_provenance,
            producer_capability_authority=producer_authority,
            producer_capabilities=producer_capabilities,
        )



_PRIVILEGED_EVENT_ROLES: dict[EvidenceKind, PrivilegedProducerRole] = {
    EvidenceKind.ATTACK_DELIVERY: PrivilegedProducerRole.ATTACK_INJECTOR,
    EvidenceKind.PROTOCOL_DELIVERY: PrivilegedProducerRole.PROTOCOL_BRIDGE,
    EvidenceKind.APPROVAL_DECISION: PrivilegedProducerRole.APPROVAL_CONTROLLER,
    EvidenceKind.RETRIEVAL_DELIVERY: PrivilegedProducerRole.RETRIEVAL_BRIDGE,
    EvidenceKind.SIDE_EFFECT_OBSERVATION: PrivilegedProducerRole.SIDE_EFFECT_OBSERVER,
    EvidenceKind.SEMANTIC_JUDGMENT: PrivilegedProducerRole.SEMANTIC_VERIFIER,
}


def _issue_verified_producer_capabilities(
    adapter: AgentAdapter,
    evidence: TrialEvidence,
) -> tuple[ProducerCapabilityAuthority | None, tuple[ProducerCapability, ...]]:
    """Issue run-local capabilities only after core exact-type authority checks succeeded."""

    if type(adapter) is EvidenceReplayAdapter:
        return None, ()

    privileged_events = tuple(
        event for event in evidence.events if event.kind in _PRIVILEGED_EVENT_ROLES
    )
    if not privileged_events:
        return None, ()

    authority = ProducerCapabilityAuthority()
    seen: set[tuple[PrivilegedProducerRole, str]] = set()
    capabilities: list[ProducerCapability] = []
    for event in privileged_events:
        role = _PRIVILEGED_EVENT_ROLES[event.kind]
        identity = (role, event.source)
        if identity in seen:
            continue
        seen.add(identity)
        capabilities.append(authority.issue(role=role, producer_id=event.source))
    return authority, tuple(capabilities)
