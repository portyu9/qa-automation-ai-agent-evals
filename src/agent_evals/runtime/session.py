"""Repeated-trial session runner for nondeterministic agent evaluation."""

from __future__ import annotations

from dataclasses import dataclass

from agent_evals.adapters.base import AgentAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.runtime.evaluator import EvaluatedTrial, TrialRunner
from agent_evals.statistics.reliability import ReliabilityReport


@dataclass(frozen=True, slots=True)
class EvaluationSessionResult:
    subject_identity: str
    scenario_identity: str
    trials: tuple[EvaluatedTrial, ...]
    reliability: ReliabilityReport

    @property
    def critical_violations(self) -> int:
        return sum(trial.critical_violations for trial in self.trials)


class EvaluationSession:
    """Run repeated isolated trials against one exact subject/scenario pair."""

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
    ) -> EvaluationSessionResult:
        if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
            raise ValueError("trials must be a positive integer")
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("k must be a positive integer")

        evaluated: list[EvaluatedTrial] = []
        for index in range(trials):
            trial_id = f"{scenario.scenario_id}:{scenario.revision}:{index:04d}"
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
        )
