"""Bounded non-authoritative operational observability.

Operational telemetry is deliberately outside deterministic grading, evidence roots, statistical
authority, and release policy.  The types in this module can describe evaluator/provider/judge/MCP
health, but they cannot mint TrialEvidence, change TrialVerdict, or satisfy a release gate.

High-cardinality correlation identifiers are retained only as diagnostic span/log attributes.
Metric labels are drawn from fixed enums.  Structured details are flat, bounded, and automatically
secret-suppressed before they can reach a sink.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SCHEMA: Literal["agent-evals/operational-event/v1"] = "agent-evals/operational-event/v1"
_SUMMARY_SCHEMA: Literal["agent-evals/operational-summary/v1"] = (
    "agent-evals/operational-summary/v1"
)
_AUTHORITY: Literal["non_authoritative_operational"] = "non_authoritative_operational"
_MAX_DETAIL_FIELDS = 16
_MAX_DETAIL_KEY_BYTES = 64
_MAX_DETAIL_VALUE_BYTES = 512
_MAX_CORRELATION_BYTES = 256
_MAX_WINDOWS = 1024
_DEFAULT_WINDOW_MS = 60_000
_DEFAULT_EVENT_BYTES = 8 * 1024
_REDACTED = "[REDACTED]"

_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "set_cookie",
    "token",
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bgh[pousr]_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"(?i)\bgithub_pat_[A-Za-z0-9_]{8,}\b"),
)

OperationalScalar = str | int | float | bool | None
SpanHook = Callable[[str, Mapping[str, str | int | bool]], None]
CounterHook = Callable[[str, int, Mapping[str, str]], None]


class OperationalObservabilityError(RuntimeError):
    """Base class for operational-observability failures."""


class OperationalCardinalityError(OperationalObservabilityError):
    """A bounded diagnostic cardinality ceiling was exceeded."""


class OperationalEventTooLargeError(OperationalObservabilityError):
    """A serialized diagnostic event exceeded its configured byte ceiling."""


class OperationalEventKind(StrEnum):
    INFO = "info"
    BLOCKED = "blocked"
    EVALUATOR_ERROR = "evaluator_error"
    JUDGE_ABSTENTION = "judge_abstention"
    JUDGE_CALIBRATION_DRIFT = "judge_calibration_drift"
    PROVIDER_INSTABILITY = "provider_instability"
    MCP_INSTABILITY = "mcp_instability"


class OperationalComponent(StrEnum):
    EVALUATOR = "evaluator"
    EVIDENCE = "evidence"
    JUDGE = "judge"
    PROVIDER = "provider"
    MCP = "mcp"
    RUNTIME = "runtime"


class OperationalReason(StrEnum):
    PRECONDITION = "precondition"
    INVALID_EVIDENCE = "invalid_evidence"
    RESOURCE_LIMIT = "resource_limit"
    EVALUATOR_EXCEPTION = "evaluator_exception"
    AUTHORITY_UNCERTAINTY = "authority_uncertainty"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_TIMEOUT = "provider_timeout"
    MCP_TRANSPORT = "mcp_transport"
    MCP_PROTOCOL = "mcp_protocol"
    JUDGE_ABSTAINED = "judge_abstained"
    JUDGE_CALIBRATION_DRIFT = "judge_calibration_drift"
    UNKNOWN = "unknown"


class OperationalEvent(BaseModel):
    """One bounded diagnostic event with permanently non-authoritative semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/operational-event/v1"] = _SCHEMA
    authority: Literal["non_authoritative_operational"] = _AUTHORITY
    kind: OperationalEventKind
    component: OperationalComponent
    observed_at_unix_ms: int = Field(ge=0, strict=True)
    campaign_id: str | None = Field(default=None, max_length=_MAX_CORRELATION_BYTES)
    trial_id: str | None = Field(default=None, max_length=_MAX_CORRELATION_BYTES)
    relation_id: str | None = Field(default=None, max_length=_MAX_CORRELATION_BYTES)
    reason: OperationalReason | None = None
    details: dict[str, OperationalScalar] = Field(default_factory=dict, max_length=_MAX_DETAIL_FIELDS)

    @field_validator("campaign_id", "trial_id", "relation_id")
    @classmethod
    def validate_correlation_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or not value:
            raise ValueError("operational correlation identifiers must be non-empty trimmed text")
        if len(value.encode("utf-8")) > _MAX_CORRELATION_BYTES:
            raise ValueError("operational correlation identifier exceeds byte ceiling")
        return value

    @field_validator("details", mode="before")
    @classmethod
    def sanitize_details(cls, value: object) -> dict[str, OperationalScalar]:
        if not isinstance(value, Mapping):
            raise ValueError("operational details must be a mapping")
        if len(value) > _MAX_DETAIL_FIELDS:
            raise ValueError(f"operational details exceed {_MAX_DETAIL_FIELDS} fields")
        sanitized: dict[str, OperationalScalar] = {}
        for raw_key, raw_value in value.items():
            if type(raw_key) is not str or not raw_key or raw_key != raw_key.strip():
                raise ValueError("operational detail keys must be non-empty trimmed exact text")
            if len(raw_key.encode("utf-8")) > _MAX_DETAIL_KEY_BYTES:
                raise ValueError("operational detail key exceeds byte ceiling")
            key = raw_key
            if _sensitive_key(key):
                sanitized[key] = _REDACTED
                continue
            sanitized[key] = _sanitize_scalar(raw_value)
        return sanitized


class OperationalWindowSummary(BaseModel):
    """Exact operational counts for one diagnostic time bucket."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start_unix_ms: int = Field(ge=0, strict=True)
    window_ms: int = Field(gt=0, strict=True)
    total_events: int = Field(ge=0, strict=True)
    blocked_by_reason: dict[str, int] = Field(
        default_factory=dict,
        max_length=len(OperationalReason),
    )
    evaluator_errors: int = Field(ge=0, strict=True)
    judge_abstentions: int = Field(ge=0, strict=True)
    judge_calibration_drifts: int = Field(ge=0, strict=True)
    provider_instability: int = Field(ge=0, strict=True)
    mcp_instability: int = Field(ge=0, strict=True)

    @field_validator("blocked_by_reason")
    @classmethod
    def validate_blocked_by_reason(cls, value: dict[str, int]) -> dict[str, int]:
        allowed = {reason.value for reason in OperationalReason}
        for reason, count in value.items():
            if reason not in allowed:
                raise ValueError("blocked operational reason is not from the bounded reason enum")
            if type(count) is not int or count < 0:
                raise ValueError("blocked operational counts must be non-negative exact integers")
        return dict(sorted(value.items()))

    @property
    def evaluator_error_rate(self) -> float:
        if self.total_events == 0:
            return 0.0
        return self.evaluator_errors / self.total_events


class OperationalSummary(BaseModel):
    """Non-authoritative operational summary; never a behavioral reliability result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/operational-summary/v1"] = _SUMMARY_SCHEMA
    authority: Literal["non_authoritative_operational"] = _AUTHORITY
    windows: tuple[OperationalWindowSummary, ...] = Field(max_length=_MAX_WINDOWS)


@dataclass(slots=True)
class _MutableWindow:
    total_events: int = 0
    blocked_by_reason: dict[str, int] = field(default_factory=dict)
    evaluator_errors: int = 0
    judge_abstentions: int = 0
    judge_calibration_drifts: int = 0
    provider_instability: int = 0
    mcp_instability: int = 0


class OperationalAggregator:
    """Streaming exact-count aggregation with bounded time-bucket cardinality."""

    def __init__(
        self,
        *,
        window_ms: int = _DEFAULT_WINDOW_MS,
        max_windows: int = _MAX_WINDOWS,
    ) -> None:
        if type(window_ms) is not int or window_ms <= 0:
            raise ValueError("operational window_ms must be a positive exact integer")
        if type(max_windows) is not int or max_windows <= 0:
            raise ValueError("operational max_windows must be a positive exact integer")
        self._window_ms = window_ms
        self._max_windows = max_windows
        self._windows: dict[int, _MutableWindow] = {}

    def record(self, event: OperationalEvent) -> None:
        if type(event) is not OperationalEvent:
            raise TypeError("operational aggregator requires exact OperationalEvent values")
        start = (event.observed_at_unix_ms // self._window_ms) * self._window_ms
        counts = self._windows.get(start)
        if counts is None:
            if len(self._windows) >= self._max_windows:
                raise OperationalCardinalityError(
                    f"operational summary exceeds configured {self._max_windows} time windows"
                )
            counts = _MutableWindow()
            self._windows[start] = counts

        counts.total_events += 1
        if event.kind is OperationalEventKind.BLOCKED:
            reason = (event.reason or OperationalReason.UNKNOWN).value
            counts.blocked_by_reason[reason] = counts.blocked_by_reason.get(reason, 0) + 1
        elif event.kind is OperationalEventKind.EVALUATOR_ERROR:
            counts.evaluator_errors += 1
        elif event.kind is OperationalEventKind.JUDGE_ABSTENTION:
            counts.judge_abstentions += 1
        elif event.kind is OperationalEventKind.JUDGE_CALIBRATION_DRIFT:
            counts.judge_calibration_drifts += 1
        elif event.kind is OperationalEventKind.PROVIDER_INSTABILITY:
            counts.provider_instability += 1
        elif event.kind is OperationalEventKind.MCP_INSTABILITY:
            counts.mcp_instability += 1

    def summary(self) -> OperationalSummary:
        windows = tuple(
            OperationalWindowSummary(
                window_start_unix_ms=start,
                window_ms=self._window_ms,
                total_events=counts.total_events,
                blocked_by_reason=dict(sorted(counts.blocked_by_reason.items())),
                evaluator_errors=counts.evaluator_errors,
                judge_abstentions=counts.judge_abstentions,
                judge_calibration_drifts=counts.judge_calibration_drifts,
                provider_instability=counts.provider_instability,
                mcp_instability=counts.mcp_instability,
            )
            for start, counts in sorted(self._windows.items())
        )
        return OperationalSummary(windows=windows)


class StructuredOperationalLogger:
    """Emit canonical JSONL diagnostics after schema-level secret suppression."""

    def __init__(self, stream: TextIO, *, max_event_bytes: int = _DEFAULT_EVENT_BYTES) -> None:
        if type(max_event_bytes) is not int or max_event_bytes <= 0:
            raise ValueError("operational log byte ceiling must be a positive exact integer")
        self._stream = stream
        self._max_event_bytes = max_event_bytes

    def emit(self, event: OperationalEvent) -> None:
        if type(event) is not OperationalEvent:
            raise TypeError("structured logger requires an exact OperationalEvent")
        line = json.dumps(
            event.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if len(line.encode("utf-8")) > self._max_event_bytes:
            raise OperationalEventTooLargeError("operational log event exceeds configured byte ceiling")
        self._stream.write(line + "\n")


class OpenTelemetryHook:
    """Optional bridge into OpenTelemetry-compatible span/counter hooks.

    Metric labels deliberately exclude campaign/trial/relation identifiers.  Those correlation
    values may be attached to spans for diagnostics, but they never become metric dimensions.
    The bridge has no return value that grading or release code can consume.
    """

    def __init__(
        self,
        *,
        span_hook: SpanHook | None = None,
        counter_hook: CounterHook | None = None,
    ) -> None:
        self._span_hook = span_hook
        self._counter_hook = counter_hook

    @classmethod
    def from_opentelemetry(
        cls,
        *,
        tracer: Any | None = None,
        meter: Any | None = None,
    ) -> OpenTelemetryHook:
        """Adapt optional OpenTelemetry API objects without adding a mandatory dependency."""

        span_hook: SpanHook | None = None
        counter_hook: CounterHook | None = None

        if tracer is not None:

            def record_span(name: str, attributes: Mapping[str, str | int | bool]) -> None:
                with tracer.start_as_current_span(name, attributes=dict(attributes)):
                    pass

            span_hook = record_span

        if meter is not None:
            counter = meter.create_counter(
                "agent_evals.operational_events",
                description="Non-authoritative agent-evals operational events",
            )

            def record_counter(
                name: str,
                amount: int,
                attributes: Mapping[str, str],
            ) -> None:
                del name
                counter.add(amount, attributes=dict(attributes))

            counter_hook = record_counter

        return cls(span_hook=span_hook, counter_hook=counter_hook)

    def emit(self, event: OperationalEvent) -> None:
        if type(event) is not OperationalEvent:
            raise TypeError("OpenTelemetry hook requires an exact OperationalEvent")
        metric_attributes = {
            "authority": event.authority,
            "kind": event.kind.value,
            "component": event.component.value,
            "reason": (event.reason or OperationalReason.UNKNOWN).value,
        }
        if self._counter_hook is not None:
            self._counter_hook("agent_evals.operational_events", 1, metric_attributes)

        if self._span_hook is not None:
            span_attributes: dict[str, str | int | bool] = dict(metric_attributes)
            if event.campaign_id is not None:
                span_attributes["campaign_id"] = event.campaign_id
            if event.trial_id is not None:
                span_attributes["trial_id"] = event.trial_id
            if event.relation_id is not None:
                span_attributes["relation_id"] = event.relation_id
            self._span_hook(f"agent_evals.{event.kind.value}", span_attributes)


def _sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _sanitize_scalar(value: object) -> OperationalScalar:
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("operational numeric details must be finite")
        return value
    if type(value) is not str:
        raise ValueError("operational details must contain only scalar JSON values")
    if len(value.encode("utf-8")) > _MAX_DETAIL_VALUE_BYTES:
        raise ValueError("operational detail text exceeds byte ceiling")
    sanitized = value
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(_REDACTED, sanitized)
    return sanitized
