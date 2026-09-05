"""Execute one agent trial and derive terminal truth from evidence-bound grading."""

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
from agent_evals.side_effect.oracle import SideEffectIdempotencyOracle
from agent_evals.side_effect.verification import (
    SideEffectObservationError,
    verify_side_effect_observation,
)
from agent_evals.retrieval.verification import RetrievalDeliveryError, verify_retrieval_delivery
from agent_evals.semantic.judge import (
    SemanticJudge,
    SemanticJudgeConfigurationError,
    validate_semantic_judge_authority,
)
from agent_evals.semantic.models import SemanticDecision, SemanticJudgeInput, SemanticJudgeResponse
from agent_evals.semantic.receipt import SemanticJudgmentReceipt
from agent_evals.semantic.verification import (
    SemanticJudgmentError,
    append_semantic_judgment,
    verify_semantic_judgment,
)


@dataclass(frozen=True, slots=True)
class EvaluatedTrial:
    evidence: TrialEvidence
    oracle_results: tuple[OracleResult, ...]
    verdict: TrialVerdict
    semantic_judgment: SemanticJudgmentReceipt | None = None

    @property
    def critical_violations(self) -> int:
        return sum(
            result.critical and result.verdict is TrialVerdict.FAIL
            for result in self.oracle_results
        )


class TrialRunner:
    """Fail-closed trial executor with non-overridable deterministic grading authority.

    Provider/runtime exceptions and failed evaluation preconditions become BLOCKED evidence. Agent
    output cannot convert missing execution evidence into PASS. Deterministic oracle failures
    always dominate semantic judgment and short-circuit semantic judge invocation entirely.
    """

    def __init__(self, *, semantic_judge: SemanticJudge | None = None) -> None:
        self._oracles = (PolicyOracle(), SideEffectIdempotencyOracle(), OutcomeOracle())
        self._semantic_judge = semantic_judge

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
            verify_retrieval_delivery(scenario, evidence)
        except RetrievalDeliveryError as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:retrieval-delivery",
                    code="retrieval_delivery_unverified",
                    reason=str(exc),
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        try:
            verify_side_effect_observation(scenario, evidence)
        except SideEffectObservationError as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:side-effect-observation",
                    code="side_effect_observation_unverified",
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
        deterministic_failed = any(result.verdict is TrialVerdict.FAIL for result in oracle_results)

        try:
            recorded_semantic = verify_semantic_judgment(scenario, evidence)
        except SemanticJudgmentError as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:semantic-judgment",
                    code="semantic_judgment_unverified",
                    reason=str(exc),
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        if deterministic_failed:
            if recorded_semantic is not None:
                return EvaluatedTrial(
                    evidence=self._append_evaluation_error(
                        evidence,
                        source="evaluator:semantic-judgment",
                        code="semantic_judgment_after_deterministic_failure",
                        reason=(
                            "recorded semantic judgment is impossible because deterministic "
                            "grading already failed and must have short-circuited the judge"
                        ),
                    ),
                    oracle_results=(),
                    verdict=TrialVerdict.BLOCKED,
                )
            return EvaluatedTrial(
                evidence=evidence,
                oracle_results=oracle_results,
                verdict=TrialVerdict.FAIL,
            )

        rubric = scenario.semantic_rubric
        if rubric is None:
            return EvaluatedTrial(
                evidence=evidence,
                oracle_results=oracle_results,
                verdict=TrialVerdict.PASS,
            )

        if recorded_semantic is not None:
            return EvaluatedTrial(
                evidence=evidence,
                oracle_results=oracle_results,
                verdict=self._semantic_verdict(recorded_semantic.decision),
                semantic_judgment=recorded_semantic,
            )

        if self._semantic_judge is None:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:semantic-judge",
                    code="semantic_judge_missing",
                    reason="scenario requires semantic grading but no calibrated judge is configured",
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )
        if evidence.final_output is None:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:semantic-judge",
                    code="semantic_candidate_missing",
                    reason="scenario requires semantic grading but the subject produced no final output",
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        try:
            profile, calibration = validate_semantic_judge_authority(self._semantic_judge)
        except (SemanticJudgeConfigurationError, Exception) as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:semantic-judge",
                    code="semantic_judge_uncalibrated",
                    reason=f"semantic judge authority is unavailable: {type(exc).__name__}",
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        judge_input = SemanticJudgeInput(
            objective=scenario.objective,
            rubric=rubric,
            candidate_output=evidence.final_output,
        )
        try:
            raw_response = await self._semantic_judge.judge(judge_input)
        except Exception as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:semantic-judge",
                    code="semantic_judge_runtime_error",
                    reason=f"semantic judge invocation failed: {type(exc).__name__}",
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        try:
            if not isinstance(raw_response, SemanticJudgeResponse):
                raise ValueError("semantic judge returned an unexpected response type")
            response = SemanticJudgeResponse.model_validate(raw_response.model_dump(mode="json"))
            receipt = SemanticJudgmentReceipt.create(
                scenario_identity=scenario.identity,
                subject_identity=subject.identity,
                subject_evidence_root=evidence.evidence_root,
                rubric=rubric,
                judge_profile=profile,
                calibration_receipt=calibration,
                judge_input=judge_input,
                response=response,
            )
            evidence = append_semantic_judgment(evidence, receipt)
        except (ValueError, ValidationError, SemanticJudgmentError) as exc:
            return EvaluatedTrial(
                evidence=self._append_evaluation_error(
                    evidence,
                    source="evaluator:semantic-judge",
                    code="semantic_judgment_invalid",
                    reason=str(exc),
                ),
                oracle_results=(),
                verdict=TrialVerdict.BLOCKED,
            )

        return EvaluatedTrial(
            evidence=evidence,
            oracle_results=oracle_results,
            verdict=self._semantic_verdict(receipt.decision),
            semantic_judgment=receipt,
        )

    @staticmethod
    def _semantic_verdict(decision: SemanticDecision) -> TrialVerdict:
        if decision is SemanticDecision.PASS:
            return TrialVerdict.PASS
        if decision is SemanticDecision.FAIL:
            return TrialVerdict.FAIL
        return TrialVerdict.INCONCLUSIVE

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
