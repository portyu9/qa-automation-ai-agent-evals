"""Shared deterministic grading authority for one precondition-closed trial."""

from __future__ import annotations

from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import TrialEvidence
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle
from agent_evals.side_effect.oracle import SideEffectIdempotencyOracle


def grade_deterministic_evidence(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> tuple[OracleResult, ...]:
    """Derive the exact framework deterministic-oracle tuple in runtime order.

    Callers must establish the shared pre-grading closure before invoking this function. The
    returned tuple is behavior-bearing: report construction compares it exactly, including oracle
    order, verdicts, reasons, and critical flags, against the finalized runtime trial.
    """
    if scenario.side_effect_idempotency is not None:
        oracles = (
            PolicyOracle(),
            SideEffectIdempotencyOracle(),
            OutcomeOracle(),
        )
    else:
        oracles = (
            PolicyOracle(),
            OutcomeOracle(),
        )
    return tuple(oracle.grade(scenario, evidence) for oracle in oracles)
