"""Pure deterministic batch regrading with stable ordered results.

Parallel execution is restricted to the same evaluator-owned deterministic precondition/oracle
kernel used by ordinary runtime grading. Semantic judges, live adapters, provider I/O, and mutable
side effects are deliberately excluded, so concurrency cannot create new grading authority or a
statistical-independence claim.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import TrialEvidence, TrialVerdict
from agent_evals.oracles.deterministic import OracleResult
from agent_evals.runtime.grading import grade_deterministic_evidence
from agent_evals.runtime.preconditions import has_blocking_evidence, verify_pregrading_closure


@dataclass(frozen=True, slots=True)
class DeterministicRegradeResult:
    index: int
    trial_id: str
    evidence_root: str
    verdict: TrialVerdict
    oracle_results: tuple[OracleResult, ...]


def deterministic_regrade_one(
    *,
    index: int,
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> DeterministicRegradeResult:
    """Regrade one finalized evidence envelope without live or semantic execution."""
    scenario = scenario.model_copy(deep=True)
    evidence = evidence.snapshot()
    if evidence.scenario_identity != scenario.identity:
        raise ValueError("regrade evidence scenario identity does not match scenario contract")
    if scenario.semantic_rubric is not None:
        raise ValueError("parallel deterministic regrade excludes semantic-judge scenarios")
    if has_blocking_evidence(evidence):
        return DeterministicRegradeResult(
            index=index,
            trial_id=evidence.trial_id,
            evidence_root=evidence.evidence_root,
            verdict=TrialVerdict.BLOCKED,
            oracle_results=(),
        )
    verify_pregrading_closure(scenario, evidence)
    oracle_results = grade_deterministic_evidence(scenario, evidence)
    verdict = (
        TrialVerdict.FAIL
        if any(result.verdict is TrialVerdict.FAIL for result in oracle_results)
        else TrialVerdict.PASS
    )
    return DeterministicRegradeResult(
        index=index,
        trial_id=evidence.trial_id,
        evidence_root=evidence.evidence_root,
        verdict=verdict,
        oracle_results=oracle_results,
    )


def deterministic_regrade_batch(
    scenario: EvaluationScenario,
    evidence: tuple[TrialEvidence, ...],
    *,
    workers: int = 1,
) -> tuple[DeterministicRegradeResult, ...]:
    """Regrade pure work items serially or in parallel while preserving input order.

    workers controls computation only. It is not evidence that trials are statistically
    independent, IID, stationary, or exchangeable.
    """
    if type(workers) is not int or workers < 1 or workers > 64:
        raise ValueError("regrade workers must be an exact integer in [1, 64]")
    if type(evidence) is not tuple:
        raise ValueError("regrade evidence must be an exact tuple")
    if workers == 1 or len(evidence) < 2:
        return tuple(
            deterministic_regrade_one(index=index, scenario=scenario, evidence=item)
            for index, item in enumerate(evidence)
        )

    with ThreadPoolExecutor(max_workers=min(workers, len(evidence))) as executor:
        futures = [
            executor.submit(
                deterministic_regrade_one,
                index=index,
                scenario=scenario,
                evidence=item,
            )
            for index, item in enumerate(evidence)
        ]
        results = tuple(future.result() for future in futures)
    return tuple(sorted(results, key=lambda result: result.index))
