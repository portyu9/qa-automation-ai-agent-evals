"""Repeated-trial session runner for nondeterministic agent evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from agent_evals.adapters.base import AgentAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.runtime.reset_isolation import (
    ResetIsolationContext,
    ResetIsolationControl,
    ResetIsolationError,
    ResetIsolationObservation,
    ResetIsolationReceipt,
    validate_reset_strategy_identity,
    verify_reset_isolation_sequence,
)
from agent_evals.runtime.sampling import (
    RandomnessControl,
    RandomnessControlContext,
    RandomnessControlObservation,
    RandomnessControlReceipt,
    RandomnessStatus,
    SamplingPolicy,
    SamplingProvenanceError,
    SessionSamplingMetadata,
    StoppingRule,
    require_independence_qualifiable_sampling,
    validate_randomness_request,
    validate_randomness_strategy_identity,
    verify_session_sampling_metadata,
)
from agent_evals.statistics.reliability import ReliabilityReport

_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_INDEPENDENCE_BASIS_LENGTH = 2_000


class IndependenceStatus(StrEnum):
    """Strength of the evidence supporting an independent-attempt interpretation."""

    UNVERIFIED = "unverified"
    OPERATOR_ASSERTED = "operator_asserted"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class IndependenceQualifiedMetrics:
    """Repeated-attempt transforms together with their explicit statistical qualification."""

    status: IndependenceStatus
    basis: str | None
    reset_strategy_name: str | None
    reset_strategy_version: str | None
    reset_receipt_roots: tuple[str, ...]
    sampling_schema_version: str
    sampling_policy: SamplingPolicy
    randomness_status: RandomnessStatus
    randomness_basis: str | None
    randomness_strategy_name: str | None
    randomness_strategy_version: str | None
    randomness_receipt_roots: tuple[str, ...]
    stopping_rule: StoppingRule
    planned_trials: int
    k: int
    pass_at_k: float
    pass_power_k: float


@dataclass(frozen=True, slots=True)
class EvaluationSessionResult:
    subject_identity: str
    scenario_identity: str
    trials: tuple[EvaluatedTrial, ...]
    reliability: ReliabilityReport
    campaign_id: str | None = None
    independence_status: IndependenceStatus = IndependenceStatus.UNVERIFIED
    independence_basis: str | None = None
    runtime_adapter_name: str | None = None
    subject_adapter: str | None = None
    subject_adapter_version: str | None = None
    reset_strategy_name: str | None = None
    reset_strategy_version: str | None = None
    reset_isolation_receipts: tuple[ResetIsolationReceipt, ...] = ()
    sampling_metadata: SessionSamplingMetadata | None = None

    def validate(self) -> None:
        """Revalidate finalized evidence, reliability, and repeated-trial provenance.

        ``campaign_id=None`` and absent runtime/sampling provenance are retained for explicitly
        constructed legacy session-result objects. Results produced by :class:`EvaluationSession`
        carry a validated campaign identity, adapter provenance, and versioned sampling metadata.

        ``operator_asserted`` remains caller-owned. ``verified`` is valid only when the complete
        evaluator-owned reset/isolation receipt sequence revalidates against finalized trials.
        Sampling metadata separately records attempt inclusion, runtime/provider randomness
        provenance, and stopping semantics; none of those fields turns reset receipts into IID proof.
        """
        if not self.trials:
            raise ValueError("evaluation session requires at least one trial")
        if self.campaign_id is not None:
            _validate_campaign_id(self.campaign_id)
        _validate_independence_metadata(
            self.independence_status,
            self.independence_basis,
        )
        _validate_session_adapter_provenance(
            self.runtime_adapter_name,
            self.subject_adapter,
            self.subject_adapter_version,
        )

        trial_ids: list[str] = []
        evidence_roots: list[str] = []
        for index, trial in enumerate(self.trials):
            evidence = trial.evidence
            if evidence.subject_identity != self.subject_identity:
                raise ValueError("trial evidence subject identity does not match session")
            if evidence.scenario_identity != self.scenario_identity:
                raise ValueError("trial evidence scenario identity does not match session")
            if evidence.trial_id in trial_ids:
                raise ValueError("session contains duplicate trial IDs")
            trial_ids.append(evidence.trial_id)
            if self.campaign_id is not None:
                expected_trial_id = _campaign_trial_id(self.campaign_id, index)
                if evidence.trial_id != expected_trial_id:
                    raise ValueError("trial ID does not match session campaign and attempt index")
            if evidence.evidence_root != trial.completion_evidence_root:
                raise ValueError("evidence root changed after evaluation finalization")
            evidence_roots.append(trial.completion_evidence_root)

        self.reliability.validate()
        expected_reliability = ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in self.trials),
            k=self.reliability.k,
            confidence_z=self.reliability.confidence_z,
        )
        if self.reliability != expected_reliability:
            raise ValueError("session reliability does not recompute from trial verdicts")

        if self.sampling_metadata is not None:
            verify_session_sampling_metadata(
                self.sampling_metadata,
                campaign_id=self.campaign_id,
                subject_identity=self.subject_identity,
                scenario_identity=self.scenario_identity,
                runtime_adapter_name=self.runtime_adapter_name,
                subject_adapter=self.subject_adapter,
                subject_adapter_version=self.subject_adapter_version,
                trial_ids=tuple(trial_ids),
            )

        if self.independence_status is IndependenceStatus.VERIFIED:
            if self.campaign_id is None:
                raise ValueError("verified independence requires a campaign identity")
            if len(self.trials) < 2:
                raise ValueError("verified independence requires at least two trials")
            if (
                self.runtime_adapter_name is None
                or self.subject_adapter is None
                or self.subject_adapter_version is None
                or self.reset_strategy_name is None
                or self.reset_strategy_version is None
            ):
                raise ValueError(
                    "verified independence requires runtime, subject-adapter, and reset provenance"
                )
            try:
                verify_reset_isolation_sequence(
                    self.reset_isolation_receipts,
                    campaign_id=self.campaign_id,
                    subject_identity=self.subject_identity,
                    scenario_identity=self.scenario_identity,
                    runtime_adapter_name=self.runtime_adapter_name,
                    subject_adapter=self.subject_adapter,
                    subject_adapter_version=self.subject_adapter_version,
                    reset_strategy_name=self.reset_strategy_name,
                    reset_strategy_version=self.reset_strategy_version,
                    trial_ids=tuple(trial_ids),
                    evidence_roots=tuple(evidence_roots),
                )
            except ResetIsolationError as exc:
                raise ValueError("verified reset/isolation receipt sequence is invalid") from exc
        elif (
            self.reset_strategy_name is not None
            or self.reset_strategy_version is not None
            or self.reset_isolation_receipts
        ):
            raise ValueError(
                "reset/isolation receipt provenance is valid only for verified independence"
            )

    @property
    def critical_violations(self) -> int:
        self.validate()
        return sum(trial.critical_violations for trial in self.trials)

    def independence_qualified_metrics(self) -> IndependenceQualifiedMetrics:
        """Return ``pass@k`` / ``pass^k`` only with explicit statistical qualification."""
        self.validate()
        if self.independence_status is IndependenceStatus.UNVERIFIED:
            raise ValueError(
                "independent-attempt pass@k/pass^k interpretation is unavailable because session "
                "independence is unverified"
            )

        sampling = require_independence_qualifiable_sampling(self.sampling_metadata)
        if sampling.planned_trials is None:
            raise SamplingProvenanceError("qualified fixed-horizon sampling lost planned_trials")
        randomness_receipt_roots = tuple(
            receipt.receipt_root for receipt in sampling.randomness_control_receipts
        )

        if self.independence_status is IndependenceStatus.OPERATOR_ASSERTED:
            if self.independence_basis is None:
                raise ValueError("operator-asserted independence is missing its basis")
            return IndependenceQualifiedMetrics(
                status=self.independence_status,
                basis=self.independence_basis,
                reset_strategy_name=None,
                reset_strategy_version=None,
                reset_receipt_roots=(),
                sampling_schema_version=sampling.schema_version,
                sampling_policy=sampling.sampling_policy,
                randomness_status=sampling.randomness_status,
                randomness_basis=sampling.randomness_basis,
                randomness_strategy_name=sampling.randomness_strategy_name,
                randomness_strategy_version=sampling.randomness_strategy_version,
                randomness_receipt_roots=randomness_receipt_roots,
                stopping_rule=sampling.stopping_rule,
                planned_trials=sampling.planned_trials,
                k=self.reliability.k,
                pass_at_k=self.reliability.pass_at_k,
                pass_power_k=self.reliability.pass_power_k,
            )

        if (
            self.reset_strategy_name is None
            or self.reset_strategy_version is None
            or not self.reset_isolation_receipts
        ):
            raise ValueError("verified independence is missing reset/isolation provenance")
        return IndependenceQualifiedMetrics(
            status=self.independence_status,
            basis=None,
            reset_strategy_name=self.reset_strategy_name,
            reset_strategy_version=self.reset_strategy_version,
            reset_receipt_roots=tuple(
                receipt.receipt_root for receipt in self.reset_isolation_receipts
            ),
            sampling_schema_version=sampling.schema_version,
            sampling_policy=sampling.sampling_policy,
            randomness_status=sampling.randomness_status,
            randomness_basis=sampling.randomness_basis,
            randomness_strategy_name=sampling.randomness_strategy_name,
            randomness_strategy_version=sampling.randomness_strategy_version,
            randomness_receipt_roots=randomness_receipt_roots,
            stopping_rule=sampling.stopping_rule,
            planned_trials=sampling.planned_trials,
            k=self.reliability.k,
            pass_at_k=self.reliability.pass_at_k,
            pass_power_k=self.reliability.pass_power_k,
        )


class EvaluationSession:
    """Run repeated trials against one exact snapshotted subject/scenario pair.

    Every invocation gets a collision-resistant campaign identity by default. Campaign identity is
    namespace/provenance only; it is not reset evidence or a statistical-independence claim.

    Sessions execute a predeclared fixed horizon: every requested attempt is included unless the
    session aborts without producing a result. The resulting ``SessionSamplingMetadata`` records
    that sampling/stopping relation explicitly. The same subject adapter object is intentionally
    reused across attempts.

    Sessions default to ``UNVERIFIED`` independence and ``UNKNOWN`` runtime/provider randomness. A
    caller may use ``OPERATOR_ASSERTED`` with an explicit textual basis. A ``VERIFIED`` campaign
    additionally requires a separately supplied ``ResetIsolationControl``. Before every post-first
    attempt, the evaluator invokes that control, accepts only a bounded digest observation,
    constructs a domain-separated receipt itself, and later revalidates the complete receipt chain
    against finalized predecessor evidence.

    ``EVALUATOR_CONTROLLED`` randomness similarly requires a separately supplied
    ``RandomnessControl``. The evaluator invokes it before every subject attempt and binds the
    returned digest-only seed/control observation into a campaign-specific receipt. Duplicate seed
    identities are rejected before the affected subject attempt executes. External/unavailable/
    unknown randomness cannot carry evaluator seed receipts.

    These controls establish only their declared evaluator-owned relations. They do not prove full
    IID behavior, stationarity, exchangeability, unbiased sampling, absence of hidden shared state,
    or that an arbitrary external target/provider implements the claimed hidden semantics.
    """

    def __init__(self, *, runner: TrialRunner | None = None) -> None:
        self._runner = runner or TrialRunner()

    async def run(
        self,
        adapter: AgentAdapter,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trials: int,
        k: int = 1,
        campaign_id: str | None = None,
        independence_status: IndependenceStatus = IndependenceStatus.UNVERIFIED,
        independence_basis: str | None = None,
        reset_control: ResetIsolationControl | None = None,
        randomness_status: RandomnessStatus = RandomnessStatus.UNKNOWN,
        randomness_basis: str | None = None,
        randomness_control: RandomnessControl | None = None,
    ) -> EvaluationSessionResult:
        if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
            raise ValueError("trials must be a positive integer")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("k must be a positive integer")
        campaign_id = _resolve_campaign_id(campaign_id)
        _validate_independence_metadata(independence_status, independence_basis)
        _validate_reset_control_request(
            independence_status,
            trials=trials,
            adapter=adapter,
            reset_control=reset_control,
        )
        validate_randomness_request(randomness_status, randomness_basis, randomness_control)
        if randomness_control is not None and _same_object(randomness_control, adapter):
            raise SamplingProvenanceError(
                "randomness control must be separate from the subject adapter"
            )

        runtime_adapter_name = _validate_runtime_adapter_name(adapter.name)
        subject = subject.snapshot()
        scenario = scenario.snapshot()
        _validate_session_adapter_provenance(
            runtime_adapter_name,
            subject.adapter,
            subject.adapter_version,
        )

        reset_strategy_name: str | None = None
        reset_strategy_version: str | None = None
        if independence_status is IndependenceStatus.VERIFIED:
            if reset_control is None:
                raise ValueError("verified independence requires a reset/isolation control")
            try:
                reset_strategy_name, reset_strategy_version = validate_reset_strategy_identity(
                    reset_control.strategy_name,
                    reset_control.strategy_version,
                )
            except Exception as exc:
                if isinstance(exc, ResetIsolationError):
                    raise
                raise ResetIsolationError(
                    "reset/isolation control strategy metadata could not be read"
                ) from None

        randomness_strategy_name: str | None = None
        randomness_strategy_version: str | None = None
        if randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED:
            if randomness_control is None:
                raise SamplingProvenanceError(
                    "evaluator-controlled randomness requires a randomness control"
                )
            try:
                randomness_strategy_name, randomness_strategy_version = (
                    validate_randomness_strategy_identity(
                        randomness_control.strategy_name,
                        randomness_control.strategy_version,
                    )
                )
            except Exception as exc:
                if isinstance(exc, SamplingProvenanceError):
                    raise
                raise SamplingProvenanceError(
                    "randomness control strategy metadata could not be read"
                ) from None

        evaluated: list[EvaluatedTrial] = []
        reset_receipts: list[ResetIsolationReceipt] = []
        randomness_receipts: list[RandomnessControlReceipt] = []
        seed_identities: set[str] = set()
        for index in range(trials):
            trial_id = _campaign_trial_id(campaign_id, index)
            if index > 0 and independence_status is IndependenceStatus.VERIFIED:
                if (
                    reset_control is None
                    or reset_strategy_name is None
                    or reset_strategy_version is None
                ):
                    raise ResetIsolationError(
                        "verified reset/isolation control disappeared during session execution"
                    )
                previous = evaluated[-1]
                context = ResetIsolationContext(
                    campaign_id=campaign_id,
                    attempt_index=index,
                    previous_trial_id=previous.evidence.trial_id,
                    next_trial_id=trial_id,
                    subject_identity=subject.identity,
                    scenario_identity=scenario.identity,
                    runtime_adapter_name=runtime_adapter_name,
                    subject_adapter=subject.adapter,
                    subject_adapter_version=subject.adapter_version,
                    previous_evidence_root=previous.completion_evidence_root,
                )
                try:
                    observation = await reset_control.reset(context=context)
                except Exception:
                    raise ResetIsolationError(
                        f"reset/isolation control failed before attempt {index}"
                    ) from None
                if type(observation) is not ResetIsolationObservation:
                    raise ResetIsolationError(
                        "reset/isolation control must return an exact ResetIsolationObservation"
                    )
                receipt = ResetIsolationReceipt.create(
                    context=context,
                    reset_strategy_name=reset_strategy_name,
                    reset_strategy_version=reset_strategy_version,
                    control_evidence_identity=observation.control_evidence_identity,
                )
                reset_receipts.append(receipt)

            if randomness_status is RandomnessStatus.EVALUATOR_CONTROLLED:
                if (
                    randomness_control is None
                    or randomness_strategy_name is None
                    or randomness_strategy_version is None
                ):
                    raise SamplingProvenanceError(
                        "evaluator randomness control disappeared during session execution"
                    )
                randomness_context = RandomnessControlContext(
                    campaign_id=campaign_id,
                    attempt_index=index,
                    trial_id=trial_id,
                    subject_identity=subject.identity,
                    scenario_identity=scenario.identity,
                    runtime_adapter_name=runtime_adapter_name,
                    subject_adapter=subject.adapter,
                    subject_adapter_version=subject.adapter_version,
                )
                try:
                    randomness_observation = await randomness_control.prepare(
                        context=randomness_context
                    )
                except Exception:
                    raise SamplingProvenanceError(
                        f"randomness control failed before attempt {index}"
                    ) from None
                if type(randomness_observation) is not RandomnessControlObservation:
                    raise SamplingProvenanceError(
                        "randomness control must return an exact RandomnessControlObservation"
                    )
                if randomness_observation.seed_identity in seed_identities:
                    raise SamplingProvenanceError(
                        "evaluator-controlled attempt seed identity was reused across attempts"
                    )
                seed_identities.add(randomness_observation.seed_identity)
                randomness_receipts.append(
                    RandomnessControlReceipt.create(
                        context=randomness_context,
                        randomness_strategy_name=randomness_strategy_name,
                        randomness_strategy_version=randomness_strategy_version,
                        seed_identity=randomness_observation.seed_identity,
                        control_evidence_identity=randomness_observation.control_evidence_identity,
                    )
                )

            evaluated.append(
                await self._runner.run(
                    adapter,
                    subject=subject,
                    scenario=scenario,
                    trial_id=trial_id,
                )
            )

        reliability = ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in evaluated),
            k=k,
        )
        sampling_metadata = SessionSamplingMetadata(
            sampling_policy=SamplingPolicy.PREDECLARED_ALL_ATTEMPTS,
            randomness_status=randomness_status,
            stopping_rule=StoppingRule.FIXED_HORIZON,
            planned_trials=trials,
            randomness_basis=randomness_basis,
            randomness_strategy_name=randomness_strategy_name,
            randomness_strategy_version=randomness_strategy_version,
            randomness_control_receipts=tuple(randomness_receipts),
        )
        result = EvaluationSessionResult(
            subject_identity=subject.identity,
            scenario_identity=scenario.identity,
            trials=tuple(evaluated),
            reliability=reliability,
            campaign_id=campaign_id,
            independence_status=independence_status,
            independence_basis=independence_basis,
            runtime_adapter_name=runtime_adapter_name,
            subject_adapter=subject.adapter,
            subject_adapter_version=subject.adapter_version,
            reset_strategy_name=reset_strategy_name,
            reset_strategy_version=reset_strategy_version,
            reset_isolation_receipts=tuple(reset_receipts),
            sampling_metadata=sampling_metadata,
        )
        result.validate()
        return result


def _resolve_campaign_id(campaign_id: str | None) -> str:
    if campaign_id is None:
        return uuid4().hex
    _validate_campaign_id(campaign_id)
    return campaign_id


def _validate_campaign_id(campaign_id: object) -> None:
    if not isinstance(campaign_id, str) or _CAMPAIGN_ID_RE.fullmatch(campaign_id) is None:
        raise ValueError(
            "campaign_id must be 1-128 ASCII letters, digits, '.', '_' or '-', starting with "
            "a letter or digit"
        )


def _validate_independence_metadata(
    status: object,
    basis: object,
) -> None:
    if type(status) is not IndependenceStatus:
        raise ValueError("independence_status must be an exact IndependenceStatus member")
    if status is IndependenceStatus.UNVERIFIED:
        if basis is not None:
            raise ValueError("unverified independence must not carry an operator assertion basis")
        return
    if status is IndependenceStatus.OPERATOR_ASSERTED:
        if not isinstance(basis, str) or not basis or basis != basis.strip():
            raise ValueError(
                "operator_asserted independence requires a non-empty, whitespace-trimmed basis"
            )
        if len(basis) > _MAX_INDEPENDENCE_BASIS_LENGTH:
            raise ValueError(
                f"independence_basis must be at most {_MAX_INDEPENDENCE_BASIS_LENGTH} characters"
            )
        return
    if status is IndependenceStatus.VERIFIED:
        if basis is not None:
            raise ValueError("verified independence must not carry an operator assertion basis")
        return
    raise ValueError("unsupported independence status")


def _validate_reset_control_request(
    status: IndependenceStatus,
    *,
    trials: int,
    adapter: AgentAdapter,
    reset_control: ResetIsolationControl | None,
) -> None:
    if status is IndependenceStatus.VERIFIED:
        if trials < 2:
            raise ValueError("verified independence requires at least two trials")
        if reset_control is None:
            raise ValueError("verified independence requires a reset/isolation control")
        if _same_object(reset_control, adapter):
            raise ValueError("reset/isolation control must be separate from the subject adapter")
        return
    if reset_control is not None:
        raise ValueError("reset/isolation control may be supplied only for verified independence")


def _same_object(left: object, right: object) -> bool:
    return left is right


def _validate_runtime_adapter_name(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("runtime adapter name must be a non-empty, whitespace-trimmed string")
    if len(value) > 256:
        raise ValueError("runtime adapter name must be at most 256 characters")
    return value


def _validate_session_adapter_provenance(
    runtime_adapter_name: object,
    subject_adapter: object,
    subject_adapter_version: object,
) -> None:
    values = (runtime_adapter_name, subject_adapter, subject_adapter_version)
    if all(value is None for value in values):
        return
    if any(value is None for value in values):
        raise ValueError("session adapter provenance must be all present or all absent")
    _validate_runtime_adapter_name(runtime_adapter_name)
    for label, value in (
        ("subject adapter", subject_adapter),
        ("subject adapter version", subject_adapter_version),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label} must be a non-empty string")
        if len(value) > 512:
            raise ValueError(f"{label} must be at most 512 characters")


def _campaign_trial_id(campaign_id: str, attempt_index: int) -> str:
    return f"campaign:{campaign_id}:attempt:{attempt_index:04d}"
