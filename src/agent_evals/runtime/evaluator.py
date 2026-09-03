"""Execute one agent trial and derive terminal truth from deterministic evidence."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from agent_evals.adapters.base import AgentAdapter, AdapterResult
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle


@dataclass(frozen=True, slots=True)
class EvaluatedTrial:
    evidence: TrialEvidence
    oracle_results: tuple[OracleResult, ...]
    verdict: TrialVerdict

    @property
    def critical_violations(self) -> int:
        return sum(result.critical and result.verdict is TrialVerdict.FAIL for result in self.oracle_results)


class TrialRunner:
    """Fail-closed trial executor.

    Provider/runtime exceptions become BLOCKED evidence. Agent output cannot convert missing
    execution evidence into PASS, and deterministic oracle failures always dominate semantic
    quality scores that may be added by higher layers.
    """

    def __init__(self) -> None:
        self._oracles = (PolicyOracle(), OutcomeOracle())

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
            result = await adapter.execute(subject=subject, scenario=scenario, trial_id=trial_id)
        except Exception as exc:  # adapter boundary: convert provider failure into structured evidence
            elapsed_ms = (perf_counter() - started) * 1000.0
            event = EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.RUNTIME_ERROR,
                source=f"adapter:{adapter.name}",
                payload={"exception_type": type(exc).__name__, "message": str(exc)},
                critical=True,
            )
            evidence = TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
                events=(event,),
                elapsed_ms=elapsed_ms,
            )
            return EvaluatedTrial(evidence=evidence, oracle_results=(), verdict=TrialVerdict.BLOCKED)

        evidence = self._to_evidence(result, subject=subject, scenario=scenario, trial_id=trial_id)
        oracle_results = tuple(oracle.grade(scenario, evidence) for oracle in self._oracles)
        verdict = (
            TrialVerdict.FAIL
            if any(result.verdict is TrialVerdict.FAIL for result in oracle_results)
            else TrialVerdict.PASS
        )
        return EvaluatedTrial(evidence=evidence, oracle_results=oracle_results, verdict=verdict)

    @staticmethod
    def _to_evidence(
        result: AdapterResult,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> TrialEvidence:
        return TrialEvidence(
            trial_id=trial_id,
            subject_identity=subject.identity,
            scenario_identity=scenario.identity,
            events=result.events,
            final_state=result.final_state,
            final_output=result.final_output,
            elapsed_ms=result.elapsed_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
        )
