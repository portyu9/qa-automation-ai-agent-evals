"""Execute one agent trial and derive terminal truth from deterministic evidence."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pydantic import ValidationError

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult, AgentAdapter
from agent_evals.adversarial.delivery import AttackDeliveryError, verify_attack_delivery
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.approval_intent import ApprovalIntentError, verify_approval_intent
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence, TrialVerdict
from agent_evals.mcp.delivery import ProtocolDeliveryError, verify_protocol_delivery
from agent_evals.oracles.deterministic import OracleResult, OutcomeOracle, PolicyOracle


@dataclass(frozen=True, slots=True)
class EvaluatedTrial:
    evidence: TrialEvidence
    oracle_results: tuple[OracleResult, ...]
    verdict: TrialVerdict

    @property
    def critical_violations(self) -> int:
        return sum(
            result.critical and result.verdict is TrialVerdict.FAIL
            for result in self.oracle_results
        )


class TrialRunner:
    """Fail-closed trial executor.

    Provider/runtime exceptions and failed evaluation preconditions become BLOCKED evidence. Agent
    output cannot convert missing execution evidence into PASS, and deterministic oracle failures
    always dominate semantic quality scores that may be added by higher layers.
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
            result = await adapter.execute(
                subject=subject,
                scenario=scenario,
                trial_id=trial_id,
            )
        except AdapterPreconditionError as exc:
            elapsed_ms = (perf_counter() - started) * 1000.0
            event = EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.EVALUATION_ERROR,
                source=f"adapter:{adapter.name}",
                payload={"code": exc.code, "reason": exc.reason},
                critical=True,
            )
            evidence = TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
                events=(event,),
                elapsed_ms=elapsed_ms,
            )
            return EvaluatedTrial(
                evidence=evidence,
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )
        except Exception as exc:  # adapter boundary: provider failure becomes structured evidence
            elapsed_ms = (perf_counter() - started) * 1000.0
            event = EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.RUNTIME_ERROR,
                source=f"adapter:{adapter.name}",
                payload={
                    "exception_type": type(exc).__name__,
                    "detail_retained": False,
                },
                critical=True,
            )
            evidence = TrialEvidence(
                trial_id=trial_id,
                subject_identity=subject.identity,
                scenario_identity=scenario.identity,
                events=(event,),
                elapsed_ms=elapsed_ms,
            )
            return EvaluatedTrial(
                evidence=evidence,
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        if not isinstance(result, AdapterResult):
            return self._invalid_adapter_result(
                adapter=adapter,
                subject=subject,
                scenario=scenario,
                trial_id=trial_id,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        try:
            evidence = self._to_evidence(
                result,
                subject=subject,
                scenario=scenario,
                trial_id=trial_id,
            )
        except ValidationError:
            return self._invalid_adapter_result(
                adapter=adapter,
                subject=subject,
                scenario=scenario,
                trial_id=trial_id,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        try:
            verify_attack_delivery(scenario, evidence)
        except AttackDeliveryError as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:attack-delivery",
                    code="attack_delivery_unverified",
                    reason=str(exc),
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        try:
            verify_protocol_delivery(evidence)
        except ProtocolDeliveryError as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:protocol-delivery",
                    code="protocol_delivery_unverified",
                    reason=str(exc),
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        try:
            verify_approval_intent(scenario, evidence)
        except ApprovalIntentError as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:approval-intent",
                    code="approval_intent_unverified",
                    reason=str(exc),
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        oracle_results = tuple(oracle.grade(scenario, evidence) for oracle in self._oracles)
        verdict = (
            TrialVerdict.FAIL
            if any(result.verdict is TrialVerdict.FAIL for result in oracle_results)
            else TrialVerdict.PASS
        )
        return EvaluatedTrial(
            evidence=evidence,
            oracle_results=oracle_results,
            verdict=verdict,
        )

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

    @staticmethod
    def _invalid_adapter_result(
        *,
        adapter: AgentAdapter,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
        elapsed_ms: float,
    ) -> EvaluatedTrial:
        event = EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.EVALUATION_ERROR,
            source=f"evaluator:adapter:{adapter.name}",
            payload={
                "code": "invalid_adapter_result",
                "reason": "adapter result failed normalized evidence validation",
            },
            critical=True,
        )
        evidence = TrialEvidence(
            trial_id=trial_id,
            subject_identity=subject.identity,
            scenario_identity=scenario.identity,
            events=(event,),
            elapsed_ms=elapsed_ms,
        )
        return EvaluatedTrial(
            evidence=evidence,
            oracle_results=(),
            verdict=TrialVerdict.BLOCKED,
        )

    @staticmethod
    def _append_evaluation_error(
        evidence: TrialEvidence,
        *,
        source: str,
        code: str,
        reason: str,
    ) -> TrialEvidence:
        event = EvidenceEvent(
            sequence=len(evidence.events),
            kind=EvidenceKind.EVALUATION_ERROR,
            source=source,
            payload={"code": code, "reason": reason},
            critical=True,
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
