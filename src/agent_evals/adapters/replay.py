"""Replay recorded evidence through the deterministic assurance engine.

Replay regrades previously observed evidence. It does not re-execute the agent, tools, provider,
or environment and therefore cannot establish fresh liveness or side-effect evidence.
"""

from __future__ import annotations

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.store import LocalEvidenceStore


class ReplayIdentityError(ValueError):
    """Recorded evidence belongs to a different trial, subject, or scenario contract."""


class EvidenceReplayAdapter:
    def __init__(self, evidence: TrialEvidence) -> None:
        self._evidence = evidence

    @classmethod
    def from_store(cls, store: LocalEvidenceStore, record_key: str) -> EvidenceReplayAdapter:
        return cls(store.read(record_key).evidence)

    @property
    def name(self) -> str:
        return "evidence-replay"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        if trial_id != self._evidence.trial_id:
            raise ReplayIdentityError(
                "recorded evidence trial identity does not match replay trial"
            )
        if subject.identity != self._evidence.subject_identity:
            raise ReplayIdentityError(
                "recorded evidence subject identity does not match replay subject"
            )
        if scenario.identity != self._evidence.scenario_identity:
            raise ReplayIdentityError(
                "recorded evidence scenario identity does not match replay scenario"
            )
        return AdapterResult(
            events=self._evidence.events,
            final_state=self._evidence.final_state,
            final_output=self._evidence.final_output,
            elapsed_ms=self._evidence.elapsed_ms,
            input_tokens=self._evidence.input_tokens,
            output_tokens=self._evidence.output_tokens,
            estimated_cost_usd=self._evidence.estimated_cost_usd,
        )
