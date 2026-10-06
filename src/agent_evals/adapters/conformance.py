"""Evaluator-owned adapter conformance boundary.

Third-party adapters may translate runtime observations into :class:`AdapterResult`, but they do
not acquire grading or evidence-producer authority by doing so. The core evaluator validates the
normalized result before evidence conversion while retaining the original adapter object for call
binding, error provenance, and exact producer-authority checks.

This layer is deliberately structural. It does not claim that a provider authenticated itself,
that remote state is truthful, or that adapter-supplied telemetry is independently verified.
"""

from __future__ import annotations

import math

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.evidence.models import EvidenceEvent

_REJECTED_NAME = "adapter-conformance-rejected"
_MAX_ADAPTER_NAME_LENGTH = 128


class AdapterConformanceError(AdapterPreconditionError):
    """An adapter or normalized result violates the evaluator-owned adapter contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(code="adapter_conformance_failed", reason=reason)


def validate_adapter_name(value: object) -> str:
    """Return one bounded safe adapter identity or fail closed."""

    if type(value) is not str:
        raise AdapterConformanceError("adapter name must be an exact string")
    if (
        not value
        or len(value) > _MAX_ADAPTER_NAME_LENGTH
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise AdapterConformanceError(
            "adapter name must contain 1..128 trimmed characters without control characters"
        )
    return value


def validate_adapter_result(value: object) -> AdapterResult:
    """Validate the exact normalized result accepted from an adapter boundary."""

    if type(value) is not AdapterResult:
        raise AdapterConformanceError("adapter must return an exact AdapterResult")

    if type(value.events) is not tuple:
        raise AdapterConformanceError("adapter events must be an exact tuple")
    for expected_sequence, event in enumerate(value.events):
        if type(event) is not EvidenceEvent:
            raise AdapterConformanceError("adapter events must contain exact EvidenceEvent values")
        if event.sequence != expected_sequence:
            raise AdapterConformanceError("adapter event sequence must be contiguous from zero")

    if type(value.final_state) is not dict:
        raise AdapterConformanceError("adapter final_state must be an exact dict")
    if value.final_output is not None and type(value.final_output) is not str:
        raise AdapterConformanceError("adapter final_output must be an exact string or None")

    _validate_nonnegative_number(value.elapsed_ms, field_name="elapsed_ms")
    _validate_nonnegative_integer(value.input_tokens, field_name="input_tokens")
    _validate_nonnegative_integer(value.output_tokens, field_name="output_tokens")
    _validate_nonnegative_number(value.estimated_cost_usd, field_name="estimated_cost_usd")
    return value


def _validate_nonnegative_integer(value: object, *, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise AdapterConformanceError(f"adapter {field_name} must be a non-negative exact integer")


def _validate_nonnegative_number(value: object, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterConformanceError(f"adapter {field_name} must be a finite non-negative number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise AdapterConformanceError(f"adapter {field_name} must be a finite non-negative number")
