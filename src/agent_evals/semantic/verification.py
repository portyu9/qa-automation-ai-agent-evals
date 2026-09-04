"""Replay-safe verification for integrity-bound semantic judgment evidence."""

from __future__ import annotations

from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.semantic.receipt import SemanticJudgmentReceipt

SEMANTIC_JUDGMENT_SOURCE = "evaluator:semantic-judge"


class SemanticJudgmentError(ValueError):
    """Persisted semantic evidence cannot prove the required judgment relation."""


def verify_semantic_judgment(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> SemanticJudgmentReceipt | None:
    """Verify one persisted terminal semantic judgment, returning None when none is recorded.

    Absence is valid here because live runtime may still need to invoke a configured judge. The
    caller decides whether absence is allowed for its execution mode. A scenario without a rubric
    must never contain semantic judgment evidence.
    """
    semantic_events = tuple(
        event for event in evidence.events if event.kind is EvidenceKind.SEMANTIC_JUDGMENT
    )
    rubric = scenario.semantic_rubric
    if rubric is None:
        if semantic_events:
            raise SemanticJudgmentError(
                "semantic judgment evidence exists for a scenario without a semantic rubric"
            )
        return None

    if not semantic_events:
        return None
    if len(semantic_events) != 1:
        raise SemanticJudgmentError("semantic rubric requires at most one recorded judgment")

    event = semantic_events[0]
    if event.sequence != len(evidence.events) - 1:
        raise SemanticJudgmentError("semantic judgment must be the terminal evaluator event")
    if event.source != SEMANTIC_JUDGMENT_SOURCE:
        raise SemanticJudgmentError("semantic judgment source is not recognized")
    if event.critical:
        raise SemanticJudgmentError("semantic judgment evidence must not claim critical authority")

    try:
        receipt = SemanticJudgmentReceipt.model_validate(event.payload)
    except ValueError as exc:
        raise SemanticJudgmentError("semantic judgment receipt is malformed") from exc

    if receipt.scenario_identity != scenario.identity:
        raise SemanticJudgmentError("semantic judgment scenario identity does not match")
    if receipt.subject_identity != evidence.subject_identity:
        raise SemanticJudgmentError("semantic judgment subject identity does not match")
    if receipt.rubric_identity != rubric.identity:
        raise SemanticJudgmentError("semantic judgment rubric identity does not match scenario")

    subject_evidence = evidence_before_semantic_judgment(evidence)
    if receipt.subject_evidence_root != subject_evidence.evidence_root:
        raise SemanticJudgmentError(
            "semantic judgment does not bind the exact pre-judgment subject evidence root"
        )
    return receipt


def evidence_before_semantic_judgment(evidence: TrialEvidence) -> TrialEvidence:
    """Reconstruct the exact trial envelope that existed before a terminal semantic event."""
    if not evidence.events or evidence.events[-1].kind is not EvidenceKind.SEMANTIC_JUDGMENT:
        raise SemanticJudgmentError("trial does not end with semantic judgment evidence")
    return TrialEvidence(
        trial_id=evidence.trial_id,
        subject_identity=evidence.subject_identity,
        scenario_identity=evidence.scenario_identity,
        events=evidence.events[:-1],
        final_state=evidence.final_state,
        final_output=evidence.final_output,
        elapsed_ms=evidence.elapsed_ms,
        input_tokens=evidence.input_tokens,
        output_tokens=evidence.output_tokens,
        estimated_cost_usd=evidence.estimated_cost_usd,
    )


def append_semantic_judgment(
    evidence: TrialEvidence,
    receipt: SemanticJudgmentReceipt,
) -> TrialEvidence:
    """Append one non-critical semantic receipt after verifying its pre-judgment binding."""
    if any(event.kind is EvidenceKind.SEMANTIC_JUDGMENT for event in evidence.events):
        raise SemanticJudgmentError("trial already contains semantic judgment evidence")
    if receipt.subject_identity != evidence.subject_identity:
        raise SemanticJudgmentError("semantic judgment subject identity does not match")
    if receipt.scenario_identity != evidence.scenario_identity:
        raise SemanticJudgmentError("semantic judgment scenario identity does not match")
    if receipt.subject_evidence_root != evidence.evidence_root:
        raise SemanticJudgmentError(
            "semantic judgment does not bind the exact pre-judgment subject evidence root"
        )

    event = EvidenceEvent(
        sequence=len(evidence.events),
        kind=EvidenceKind.SEMANTIC_JUDGMENT,
        source=SEMANTIC_JUDGMENT_SOURCE,
        payload=receipt.model_dump(mode="json"),
        critical=False,
    )
    return TrialEvidence(
        trial_id=evidence.trial_id,
        subject_identity=evidence.subject_identity,
        scenario_identity=evidence.scenario_identity,
        events=(*evidence.events, event),
        final_state=evidence.final_state,
        final_output=evidence.final_output,
        elapsed_ms=evidence.elapsed_ms,
        input_tokens=evidence.input_tokens,
        output_tokens=evidence.output_tokens,
        estimated_cost_usd=evidence.estimated_cost_usd,
    )
