"""Provider-neutral JSON runtime adapter.

The remote runtime may return terminal output/state and non-authoritative usage telemetry. It may
not supply framework EvidenceEvent objects or choose evaluator-owned evidence kinds/sources.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind

_ALLOWED_RESPONSE_KEYS = frozenset(
    {
        "output",
        "state",
        "input_tokens",
        "output_tokens",
        "estimated_cost_usd",
    }
)


@dataclass(frozen=True, slots=True)
class JsonRuntimeResponse:
    """One bounded transport response from a distinct JSON runtime."""

    status_code: int
    body: Mapping[str, object]
    request_id: str | None = None
    model_revision: str | None = None
    elapsed_ms: float = 0.0


JsonRuntimeTransport = Callable[
    [dict[str, object]],
    JsonRuntimeResponse | Awaitable[JsonRuntimeResponse],
]


class JsonHttpRuntimeAdapter:
    """Normalize a remote JSON runtime without granting it evidence-producer authority."""

    def __init__(
        self,
        transport: JsonRuntimeTransport,
        *,
        name: str = "json-http-runtime",
    ) -> None:
        self._transport = transport
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
        request = {
            "schema_version": "agent-evals/json-runtime-request/v1",
            "trial_id": trial_id,
            "subject_identity": subject.identity,
            "scenario_identity": scenario.identity,
            "objective": scenario.objective,
            "max_turns": scenario.authority.max_turns,
        }
        raw = self._transport(request)
        resolved: object
        if inspect.isawaitable(raw):
            resolved = await raw
        else:
            resolved = raw
        if type(resolved) is not JsonRuntimeResponse:
            raise AdapterPreconditionError(
                code="runtime_response_invalid",
                reason="JSON runtime transport returned an invalid response object",
            )
        response = resolved
        if type(response.status_code) is not int or not 200 <= response.status_code < 300:
            raise AdapterPreconditionError(
                code="runtime_unavailable",
                reason="JSON runtime did not return a successful response",
            )
        if type(response.body) is not dict:
            raise AdapterPreconditionError(
                code="runtime_response_invalid",
                reason="JSON runtime response body must be an exact object",
            )
        unexpected = set(response.body) - _ALLOWED_RESPONSE_KEYS
        if unexpected:
            raise AdapterPreconditionError(
                code="runtime_response_invalid",
                reason="JSON runtime response contains unsupported fields",
            )

        output = response.body.get("output")
        if output is not None and type(output) is not str:
            raise AdapterPreconditionError(
                code="runtime_response_invalid",
                reason="JSON runtime output must be an exact string or null",
            )
        state = response.body.get("state", {})
        if type(state) is not dict:
            raise AdapterPreconditionError(
                code="runtime_response_invalid",
                reason="JSON runtime state must be an exact object",
            )

        input_tokens = _strict_nonnegative_int(response.body.get("input_tokens", 0), "input_tokens")
        output_tokens = _strict_nonnegative_int(
            response.body.get("output_tokens", 0),
            "output_tokens",
        )
        estimated_cost = _strict_nonnegative_number(
            response.body.get("estimated_cost_usd", 0.0),
            "estimated_cost_usd",
        )
        elapsed_ms = _strict_nonnegative_number(response.elapsed_ms, "elapsed_ms")

        events: tuple[EvidenceEvent, ...] = ()
        if output is not None:
            metadata: dict[str, object] = {"output": output}
            if response.request_id is not None:
                metadata["provider_request_id"] = _bounded_metadata(
                    response.request_id,
                    "request_id",
                )
            if response.model_revision is not None:
                metadata["provider_model_revision"] = _bounded_metadata(
                    response.model_revision,
                    "model_revision",
                )
            events = (
                EvidenceEvent(
                    sequence=0,
                    kind=EvidenceKind.OUTPUT,
                    source="json-http-runtime:normalized-output",
                    payload=metadata,
                ),
            )

        return AdapterResult(
            events=events,
            final_state=dict(state),
            final_output=output,
            elapsed_ms=elapsed_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost,
        )


def _strict_nonnegative_int(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise AdapterPreconditionError(
            code="runtime_response_invalid",
            reason=f"JSON runtime {field_name} must be a non-negative exact integer",
        )
    return value


def _strict_nonnegative_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterPreconditionError(
            code="runtime_response_invalid",
            reason=f"JSON runtime {field_name} must be a finite non-negative number",
        )
    normalized = float(value)
    if normalized < 0.0 or normalized == float("inf") or normalized != normalized:
        raise AdapterPreconditionError(
            code="runtime_response_invalid",
            reason=f"JSON runtime {field_name} must be a finite non-negative number",
        )
    return normalized


def _bounded_metadata(value: object, field_name: str) -> str:
    if type(value) is not str or not value or len(value) > 256:
        raise AdapterPreconditionError(
            code="runtime_response_invalid",
            reason=f"JSON runtime {field_name} must contain 1..256 characters",
        )
    return value
