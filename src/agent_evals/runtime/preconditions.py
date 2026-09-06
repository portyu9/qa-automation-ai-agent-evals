"""Shared fail-closed evidence checks required before deterministic trial grading."""

from __future__ import annotations

from agent_evals.adversarial.delivery import AttackDeliveryError, verify_attack_delivery
from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.approval_intent import ApprovalIntentError, verify_approval_intent
from agent_evals.evidence.models import EvidenceKind, TrialEvidence
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.retrieval.verification import RetrievalDeliveryError, verify_retrieval_delivery
from agent_evals.side_effect.verification import (
    SideEffectObservationError,
    verify_side_effect_observation,
)

_BLOCKING_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.EVALUATION_ERROR,
        EvidenceKind.RUNTIME_ERROR,
    }
)


class EvaluationPreconditionError(ValueError):
    """One normalized evaluator-owned pre-grading closure failure."""

    def __init__(self, *, source: str, code: str, reason: str) -> None:
        super().__init__(reason)
        self.source = source
        self.code = code
        self.reason = reason


def has_blocking_evidence(evidence: TrialEvidence) -> bool:
    """Return whether execution already contains evaluator/runtime blocking evidence."""
    return any(event.kind in _BLOCKING_EVIDENCE_KINDS for event in evidence.events)


def verify_pregrading_closure(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> None:
    """Run the exact semantic preconditions required before deterministic grading.

    Ordering is behavior-bearing because the first unresolved evaluator relation determines the
    structured error recorded by ``TrialRunner``. Keep this sequence aligned with the documented
    runtime contract rather than adding verifier calls independently at downstream boundaries.
    """
    try:
        verify_attack_delivery(scenario, evidence)
    except AttackDeliveryError as exc:
        raise EvaluationPreconditionError(
            source="evaluator:attack-delivery",
            code="attack_delivery_unverified",
            reason=str(exc),
        ) from exc

    try:
        verify_protocol_delivery(evidence)
    except ProtocolDeliveryError as exc:
        raise EvaluationPreconditionError(
            source="evaluator:protocol-delivery",
            code="protocol_delivery_unverified",
            reason=str(exc),
        ) from exc

    try:
        verify_retrieval_delivery(scenario, evidence)
    except RetrievalDeliveryError as exc:
        raise EvaluationPreconditionError(
            source="evaluator:retrieval-delivery",
            code="retrieval_delivery_unverified",
            reason=str(exc),
        ) from exc

    try:
        verify_side_effect_observation(scenario, evidence)
    except SideEffectObservationError as exc:
        raise EvaluationPreconditionError(
            source="evaluator:side-effect-observation",
            code="side_effect_observation_unverified",
            reason=str(exc),
        ) from exc

    try:
        verify_approval_intent(scenario, evidence)
    except ApprovalIntentError as exc:
        raise EvaluationPreconditionError(
            source="evaluator:approval-intent",
            code="approval_intent_unverified",
            reason=str(exc),
        ) from exc
