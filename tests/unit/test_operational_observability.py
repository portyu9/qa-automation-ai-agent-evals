from __future__ import annotations

import io
import json

import pytest
from pydantic import ValidationError

from agent_evals.runtime.observability import (
    OpenTelemetryHook,
    OperationalAggregator,
    OperationalCardinalityError,
    OperationalComponent,
    OperationalEvent,
    OperationalEventKind,
    OperationalReason,
    StructuredOperationalLogger,
)


def _event(
    *,
    kind: OperationalEventKind,
    observed_at_unix_ms: int = 1_000,
    reason: OperationalReason | None = None,
    details: dict[str, object] | None = None,
) -> OperationalEvent:
    return OperationalEvent(
        kind=kind,
        component=OperationalComponent.EVALUATOR,
        observed_at_unix_ms=observed_at_unix_ms,
        campaign_id="campaign-1",
        trial_id="trial-1",
        relation_id="relation-1",
        reason=reason,
        details=details or {},
    )


def test_structured_event_suppresses_secret_keys_and_tokens_before_sink() -> None:
    event = _event(
        kind=OperationalEventKind.INFO,
        details={
            "authorization": "Bearer secret-token-value",
            "message": "provider returned Bearer abcdefghijklmnop and sk-abcdefghijkl",
            "attempt": 2,
        },
    )
    stream = io.StringIO()
    StructuredOperationalLogger(stream).emit(event)

    payload = json.loads(stream.getvalue())
    assert payload["authority"] == "non_authoritative_operational"
    assert payload["details"]["authorization"] == "[REDACTED]"
    assert "secret-token-value" not in stream.getvalue()
    assert "abcdefghijklmnop" not in stream.getvalue()
    assert "sk-abcdefghijkl" not in stream.getvalue()
    assert payload["details"]["attempt"] == 2


def test_operational_details_and_correlation_cardinality_are_bounded() -> None:
    with pytest.raises(ValidationError, match="operational details exceed"):
        _event(
            kind=OperationalEventKind.INFO,
            details={f"k-{index}": index for index in range(17)},
        )

    with pytest.raises(ValidationError, match="correlation"):
        OperationalEvent(
            kind=OperationalEventKind.INFO,
            component=OperationalComponent.RUNTIME,
            observed_at_unix_ms=0,
            campaign_id="x" * 257,
        )


def test_operational_summary_keeps_health_signals_separate_from_subject_reliability() -> None:
    aggregator = OperationalAggregator(window_ms=1_000)
    aggregator.record(
        _event(
            kind=OperationalEventKind.BLOCKED,
            observed_at_unix_ms=1_001,
            reason=OperationalReason.PRECONDITION,
        )
    )
    aggregator.record(
        _event(
            kind=OperationalEventKind.BLOCKED,
            observed_at_unix_ms=1_002,
            reason=OperationalReason.PRECONDITION,
        )
    )
    aggregator.record(_event(kind=OperationalEventKind.EVALUATOR_ERROR, observed_at_unix_ms=1_003))
    aggregator.record(
        OperationalEvent(
            kind=OperationalEventKind.JUDGE_ABSTENTION,
            component=OperationalComponent.JUDGE,
            observed_at_unix_ms=2_001,
            reason=OperationalReason.JUDGE_ABSTAINED,
        )
    )
    aggregator.record(
        OperationalEvent(
            kind=OperationalEventKind.JUDGE_CALIBRATION_DRIFT,
            component=OperationalComponent.JUDGE,
            observed_at_unix_ms=2_002,
            reason=OperationalReason.JUDGE_CALIBRATION_DRIFT,
        )
    )
    aggregator.record(
        OperationalEvent(
            kind=OperationalEventKind.PROVIDER_INSTABILITY,
            component=OperationalComponent.PROVIDER,
            observed_at_unix_ms=2_003,
            reason=OperationalReason.PROVIDER_TIMEOUT,
        )
    )
    aggregator.record(
        OperationalEvent(
            kind=OperationalEventKind.MCP_INSTABILITY,
            component=OperationalComponent.MCP,
            observed_at_unix_ms=2_004,
            reason=OperationalReason.MCP_TRANSPORT,
        )
    )

    summary = aggregator.summary()
    assert summary.authority == "non_authoritative_operational"
    assert len(summary.windows) == 2

    first, second = summary.windows
    assert first.blocked_by_reason == {"precondition": 2}
    assert first.evaluator_errors == 1
    assert first.evaluator_error_rate == 1 / 3
    assert second.judge_abstentions == 1
    assert second.judge_calibration_drifts == 1
    assert second.provider_instability == 1
    assert second.mcp_instability == 1
    assert "passes" not in second.model_fields
    assert "failures" not in second.model_fields


def test_operational_window_cardinality_fails_closed_instead_of_unbounded_growth() -> None:
    aggregator = OperationalAggregator(window_ms=1_000, max_windows=2)
    aggregator.record(_event(kind=OperationalEventKind.INFO, observed_at_unix_ms=0))
    aggregator.record(_event(kind=OperationalEventKind.INFO, observed_at_unix_ms=1_000))

    with pytest.raises(OperationalCardinalityError, match="time windows"):
        aggregator.record(_event(kind=OperationalEventKind.INFO, observed_at_unix_ms=2_000))


def test_opentelemetry_hook_uses_fixed_metric_labels_and_span_only_correlations() -> None:
    metric_calls: list[tuple[str, int, dict[str, str]]] = []
    span_calls: list[tuple[str, dict[str, str | int | bool]]] = []

    hook = OpenTelemetryHook(
        counter_hook=lambda name, amount, attrs: metric_calls.append((name, amount, dict(attrs))),
        span_hook=lambda name, attrs: span_calls.append((name, dict(attrs))),
    )
    event = _event(
        kind=OperationalEventKind.BLOCKED,
        reason=OperationalReason.AUTHORITY_UNCERTAINTY,
    )
    hook.emit(event)

    metric_name, amount, metric_attributes = metric_calls[0]
    assert metric_name == "agent_evals.operational_events"
    assert amount == 1
    assert metric_attributes == {
        "authority": "non_authoritative_operational",
        "kind": "blocked",
        "component": "evaluator",
        "reason": "authority_uncertainty",
    }
    assert "trial_id" not in metric_attributes
    assert span_calls[0][1]["campaign_id"] == "campaign-1"
    assert span_calls[0][1]["trial_id"] == "trial-1"
    assert span_calls[0][1]["relation_id"] == "relation-1"


class _FakeSpan:
    def __enter__(self) -> _FakeSpan:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb


class _FakeTracer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def start_as_current_span(self, name: str, *, attributes: dict[str, object]) -> _FakeSpan:
        self.calls.append((name, attributes))
        return _FakeSpan()


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, object]]] = []

    def add(self, amount: int, *, attributes: dict[str, object]) -> None:
        self.calls.append((amount, attributes))


class _FakeMeter:
    def __init__(self) -> None:
        self.counter = _FakeCounter()

    def create_counter(self, name: str, *, description: str) -> _FakeCounter:
        assert name == "agent_evals.operational_events"
        assert description
        return self.counter


def test_optional_opentelemetry_api_objects_need_no_runtime_dependency() -> None:
    tracer = _FakeTracer()
    meter = _FakeMeter()
    hook = OpenTelemetryHook.from_opentelemetry(tracer=tracer, meter=meter)

    hook.emit(_event(kind=OperationalEventKind.EVALUATOR_ERROR))

    assert tracer.calls[0][0] == "agent_evals.evaluator_error"
    assert meter.counter.calls[0][0] == 1
