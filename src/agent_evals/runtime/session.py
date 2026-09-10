"""Repeated-trial session runner for nondeterministic agent evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from agent_evals.adapters.base import AgentAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.statistics.reliability import ReliabilityReport

_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class EvaluationSessionResult:
    subject_identity: str
    scenario_identity: str
    trials: tuple[EvaluatedTrial, ...]
    reliability: ReliabilityReport
    campaign_id: str | None = None

    def validate(self) -> None:
        """Revalidate session identity, finalized evidence, and reliability before release use.

        ``campaign_id=None`` is retained for explicitly constructed legacy/session-result objects.
        Results produced by :class:`EvaluationSession` always carry a validated campaign identity
        and bind it into every trial ID.
        """
        if not self.trials:
            raise ValueError("evaluation session requires at least one trial")
        if self.campaign_id is not None:
            _validate_campaign_id(self.campaign_id)

        trial_ids: set[str] = set()
        for index, trial in enumerate(self.trials):
            evidence = trial.evidence
            if evidence.subject_identity != self.subject_identity:
                raise ValueError("trial evidence subject identity does not match session")
            if evidence.scenario_identity != self.scenario_identity:
                raise ValueError("trial evidence scenario identity does not match session")
            if evidence.trial_id in trial_ids:
                raise ValueError("session contains duplicate trial IDs")
            trial_ids.add(evidence.trial_id)
            if self.campaign_id is not None:
                expected_trial_id = _campaign_trial_id(self.campaign_id, index)
                if evidence.trial_id != expected_trial_id:
                    raise ValueError("trial ID does not match session campaign and attempt index")
            if evidence.evidence_root != trial.completion_evidence_root:
                raise ValueError("evidence root changed after evaluation finalization")

        self.reliability.validate()
        expected_reliability = ReliabilityReport.from_verdicts(
            tuple(trial.verdict for trial in self.trials),
            k=self.reliability.k,
            confidence_z=self.reliability.confidence_z,
        )
        if self.reliability != expected_reliability:
            raise ValueError("session reliability does not recompute from trial verdicts")

    @property
    def critical_violations(self) -> int:
        self.validate()
        return sum(trial.critical_violations for trial in self.trials)


class EvaluationSession:
    """Run repeated trials against one exact snapshotted subject/scenario pair.

    Every invocation gets a collision-resistant campaign identity by default. Callers may supply a
    stable campaign ID when an external evaluation campaign already owns that namespace. Campaign
    IDs are persisted inside trial IDs; they are opaque identifiers, not authentication or signer
    identities, and should not contain secrets.

    The same adapter object is intentionally reused across attempts. This class isolates evaluator-
    owned contract objects through snapshots, but it does not reset provider/application/session/
    target-system state and does not automatically materialize ``scenario.initial_state``. A unique
    campaign identity prevents cross-campaign trial/evidence-key collisions; it does **not** prove
    environmental reset or statistical independence. Any reset required for an independent-attempt
    reliability interpretation belongs to the adapter/operator integration.
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
    ) -> EvaluationSessionResult:
        if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
            raise ValueError("trials must be a positive integer")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("k must be a positive integer")
        campaign_id = _resolve_campaign_id(campaign_id)

        subject = subject.snapshot()
        scenario = scenario.snapshot()
        evaluated: list[EvaluatedTrial] = []
        for index in range(trials):
            trial_id = _campaign_trial_id(campaign_id, index)
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
        return EvaluationSessionResult(
            subject_identity=subject.identity,
            scenario_identity=scenario.identity,
            trials=tuple(evaluated),
            reliability=reliability,
            campaign_id=campaign_id,
        )


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


def _campaign_trial_id(campaign_id: str, attempt_index: int) -> str:
    return f"campaign:{campaign_id}:attempt:{attempt_index:04d}"
