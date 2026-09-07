"""Narrow adapter boundary between the assurance engine and an agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent


class AdapterPreconditionError(RuntimeError):
    """A controlled evaluation prerequisite could not be satisfied by an adapter.

    This is distinct from a provider/runtime failure. The code and reason are intended for durable
    evaluation evidence, so callers must never place secrets, raw attack payloads, or provider
    exception detail in either field.
    """

    def __init__(self, *, code: str, reason: str) -> None:
        if not code or not code.replace("_", "").isalnum() or code.lower() != code:
            raise ValueError("adapter precondition code must be lowercase alphanumeric/underscore")
        if not reason or len(reason) > 512:
            raise ValueError("adapter precondition reason must contain 1..512 characters")
        self.code = code
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Observable result returned by an adapter after one trial execution.

    Empty event and state collections are valid observations. This keeps provider adapters free to
    report a state-only or event-only result without manufacturing placeholder evidence.

    Repeated-session environmental isolation is not encoded in this result. The adapter/operator
    integration owns any provider, application, session, memory, or external-target reset needed
    to make separate executions independent; the evaluator detaches and grades only the normalized
    observations returned for the current trial.
    """

    events: tuple[EvidenceEvent, ...] = ()
    final_state: dict[str, object] = field(default_factory=dict)
    final_output: str | None = None
    elapsed_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0


class AgentAdapter(Protocol):
    """Minimal runtime contract required by the core evaluator.

    Adapters translate provider-specific execution into normalized observable evidence. They do
    not grade their own behavior and they do not own the release decision.

    Turn-budget enforcement is deliberately runtime-owned. An adapter that owns a multi-turn
    execution loop must bind ``scenario.authority.max_turns`` to that runtime's actual turn limiter.
    If the integration cannot establish or enforce that bound, it must fail closed rather than
    return gradeable evidence that implies the bound was honored. A runtime-confirmed turn-budget
    exhaustion must become critical ``POLICY_VIOLATION`` evidence so deterministic policy grading
    can resolve the subject failure. The provider-neutral core independently rederives tool-call
    and handoff budgets from normalized events; it does not infer hidden provider/runtime turns or
    require adapters to manufacture a synthetic turn event.

    For repeated-session use, an adapter/operator integration is also responsible for whatever
    system-under-test isolation its reliability claim requires. ``EvaluationSession`` intentionally
    reuses the supplied adapter object and does not reset external systems or automatically apply
    ``EvaluationScenario.initial_state``. Evaluator-owned subject/scenario/evidence snapshots are
    isolated separately from provider, application, memory, session, and target-system state.
    """

    @property
    def name(self) -> str: ...

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult: ...
