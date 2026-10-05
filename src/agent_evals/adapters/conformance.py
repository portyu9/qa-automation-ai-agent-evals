"""Evaluator-owned adapter conformance boundary.

Third-party adapters may translate runtime observations into :class:`AdapterResult`, but they do
not acquire grading or evidence-producer authority by doing so. The public evaluator wraps every
adapter in this exact framework type before execution and validates the normalized result before
the core grading engine can accept it.

This layer is deliberately structural. It does not claim that a provider authenticated itself,
that remote state is truthful, or that adapter-supplied telemetry is independently verified.
"""

from __future__ import annotations

import math
import re

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult, AgentAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent

_REJECTED_NAME = "adapter-conformance-rejected"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")


class AdapterConformanceError(AdapterPreconditionError):
    """An adapter or normalized result violates the evaluator-owned adapter contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(code="adapter_conformance_failed", reason=reason)


def validate_adapter_name(value: object) -> str:
    """Return one bounded canonical adapter name or fail closed."""

    if type(value) is not str or _NAME_RE.fullmatch(value) is None:
        raise AdapterConformanceError(
            "adapter name must be 1..128 lowercase ASCII letters, digits, dot, colon, dash or underscore"
        )
    return value


def validate_adapter_result(value: object) -> AdapterResult:
    """Validate the exact normalized result accepted from an adapter boundary."""

    if type(value) is not AdapterResult:
        raise AdapterConformanceError("adapter must return an exact AdapterResult")

    if type(value.events) is not tuple:
        raise AdapterConformanceError("adapter events must be an exact tuple")
    expected_sequence = 0
    for event in value.events:
        if type(event) is not EvidenceEvent:
            raise AdapterConformanceError("adapter events must contain exact EvidenceEvent values")
        if event.sequence != expected_sequence:
            raise AdapterConformanceError("adapter event sequence must be contiguous from zero")
        expected_sequence += 1

    if type(value.final_state) is not dict:
        raise AdapterConformanceError("adapter final_state must be an exact dict")
    if value.final_output is not None and type(value.final_output) is not str:
        raise AdapterConformanceError("adapter final_output must be an exact string or None")

    _validate_nonnegative_number(value.elapsed_ms, field_name="elapsed_ms")
    _validate_nonnegative_integer(value.input_tokens, field_name="input_tokens")
    _validate_nonnegative_integer(value.output_tokens, field_name="output_tokens")
    _validate_nonnegative_number(value.estimated_cost_usd, field_name="estimated_cost_usd")
    return value


class ConformanceCheckedAdapter:
    """Exact evaluator-owned wrapper that validates any adapter before core grading."""

    def __init__(self, adapter: AgentAdapter) -> None:
        self._adapter = adapter

    @property
    def name(self) -> str:
        try:
            return validate_adapter_name(self._adapter.name)
        except Exception:
            return _REJECTED_NAME

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        try:
            raw_name = self._adapter.name
        except Exception as exc:
            raise AdapterConformanceError("adapter name could not be read safely") from exc
        validate_adapter_name(raw_name)
        result = await self._adapter.execute(
            subject=subject,
            scenario=scenario,
            trial_id=trial_id,
        )
        return validate_adapter_result(result)


def conformance_checked(adapter: AgentAdapter) -> AgentAdapter:
    """Wrap one adapter exactly once in the evaluator-owned conformance boundary."""

    if type(adapter) is ConformanceCheckedAdapter:
        return adapter
    return ConformanceCheckedAdapter(adapter)


def authority_adapter(adapter: AgentAdapter) -> AgentAdapter:
    """Return the underlying producer only for the exact framework conformance wrapper.

    This helper exists solely so the core evaluator can preserve its existing exact-type producer
    capability checks. A user-defined wrapper or subclass is never unwrapped.
    """

    if type(adapter) is ConformanceCheckedAdapter:
        return adapter._adapter
    return adapter


def _validate_nonnegative_integer(value: object, *, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise AdapterConformanceError(f"adapter {field_name} must be a non-negative exact integer")


def _validate_nonnegative_number(value: object, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterConformanceError(f"adapter {field_name} must be a finite non-negative number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise AdapterConformanceError(f"adapter {field_name} must be a finite non-negative number")
