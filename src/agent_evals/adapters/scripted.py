"""Deterministic adapter used for harness tests, examples, and replayable regressions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint

Script = Callable[[SubjectFingerprint, EvaluationScenario, str], AdapterResult]


class ScriptedAdapter:
    def __init__(self, script: Script, *, name: str = "scripted") -> None:
        self._script = script
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        result = self._script(subject, scenario, trial_id)
        normalized = tuple(
            event.model_copy(update={"sequence": index}) for index, event in enumerate(result.events)
        )
        return replace(result, events=normalized)
