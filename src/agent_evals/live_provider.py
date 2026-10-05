"""Bounded live-provider canary semantics.

Live canaries are historical observations, not provider attestations. Provider transport/rate
failures remain uncertainty and never become subject FAIL. A subject failure is recorded only when
a structurally valid successful response violates the predeclared behavioral assertion.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class CanaryDisposition(StrEnum):
    OBSERVED = "observed"
    SUBJECT_FAILURE = "subject_failure"
    PROVIDER_UNCERTAIN = "provider_uncertain"


@dataclass(frozen=True, slots=True)
class ProviderCanaryLimits:
    max_attempts: int = 3
    request_timeout_seconds: float = 15.0
    wall_clock_seconds: float = 45.0
    max_requests_per_minute: int = 6
    max_input_tokens: int = 256
    max_output_tokens: int = 64
    input_usd_per_million: float = 0.0
    output_usd_per_million: float = 0.0
    max_estimated_cost_usd: float = 0.01

    def __post_init__(self) -> None:
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be an exact integer in 1..5")
        if type(self.max_requests_per_minute) is not int or not 1 <= self.max_requests_per_minute <= 60:
            raise ValueError("max_requests_per_minute must be an exact integer in 1..60")
        for name in ("max_input_tokens", "max_output_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive exact integer")
        for name in (
            "request_timeout_seconds",
            "wall_clock_seconds",
            "input_usd_per_million",
            "output_usd_per_million",
            "max_estimated_cost_usd",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a finite non-negative number")
            normalized = float(value)
            if not math.isfinite(normalized) or normalized < 0.0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if self.request_timeout_seconds <= 0.0 or self.wall_clock_seconds <= 0.0:
            raise ValueError("request and wall-clock ceilings must be positive")
        if self.request_timeout_seconds > self.wall_clock_seconds:
            raise ValueError("request timeout cannot exceed the wall-clock ceiling")
        if self.worst_case_cost_usd > self.max_estimated_cost_usd:
            raise ValueError("configured token/rate bounds exceed the canary cost ceiling")

    @property
    def worst_case_cost_usd(self) -> float:
        return (
            self.max_input_tokens * self.input_usd_per_million
            + self.max_output_tokens * self.output_usd_per_million
        ) / 1_000_000.0

    @property
    def min_request_interval_seconds(self) -> float:
        return 60.0 / self.max_requests_per_minute


@dataclass(frozen=True, slots=True)
class ProviderCanaryResponse:
    status_code: int
    output: str | None = None
    request_id: str | None = None
    model_revision: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    retry_after_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderCanaryObservation:
    schema_version: str
    disposition: CanaryDisposition
    attempts: int
    provider_request_id: str | None
    provider_model_revision: str | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    reason: str
    historical_observation: bool = True
    provider_attestation: bool = False

    def canonical_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "disposition": self.disposition,
                "attempts": self.attempts,
                "provider_request_id": self.provider_request_id,
                "provider_model_revision": self.provider_model_revision,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "estimated_cost_usd": self.estimated_cost_usd,
                "reason": self.reason,
                "historical_observation": self.historical_observation,
                "provider_attestation": self.provider_attestation,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )


ProviderCanaryTransport = Callable[[float], ProviderCanaryResponse]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


def run_provider_canary(
    transport: ProviderCanaryTransport,
    *,
    expected_substring: str,
    limits: ProviderCanaryLimits,
    clock: Clock = time.monotonic,
    sleep: Sleeper = time.sleep,
) -> ProviderCanaryObservation:
    """Run one bounded live canary with deterministic retry classification."""

    if type(expected_substring) is not str or not expected_substring or len(expected_substring) > 256:
        raise ValueError("expected_substring must contain 1..256 characters")

    started = clock()
    last_response: ProviderCanaryResponse | None = None
    for attempt in range(1, limits.max_attempts + 1):
        if clock() - started >= limits.wall_clock_seconds:
            return _uncertain(attempt - 1, last_response, "wall-clock ceiling reached")
        try:
            response = transport(limits.request_timeout_seconds)
        except TimeoutError:
            if attempt == limits.max_attempts:
                return _uncertain(attempt, last_response, "provider request timed out")
            if not _sleep_within_wall(
                limits.min_request_interval_seconds,
                started=started,
                limits=limits,
                clock=clock,
                sleep=sleep,
            ):
                return _uncertain(attempt, last_response, "wall-clock ceiling reached during retry")
            continue

        if type(response) is not ProviderCanaryResponse:
            return _uncertain(attempt, last_response, "provider transport returned invalid response")
        last_response = response

        validation_error = _validate_response(response, limits)
        if validation_error is not None:
            return _uncertain(attempt, response, validation_error)

        if response.status_code in _RETRYABLE_STATUS:
            if attempt == limits.max_attempts:
                return _uncertain(attempt, response, "retryable provider failure exhausted attempts")
            delay = limits.min_request_interval_seconds
            if response.retry_after_seconds is not None:
                delay = max(delay, response.retry_after_seconds)
            if not _sleep_within_wall(
                delay,
                started=started,
                limits=limits,
                clock=clock,
                sleep=sleep,
            ):
                return _uncertain(attempt, response, "wall-clock ceiling reached during retry")
            continue

        if not 200 <= response.status_code < 300:
            return _uncertain(attempt, response, "provider returned a non-retryable error")

        if response.output is None:
            return _uncertain(attempt, response, "successful provider response had no text output")

        cost = _estimated_cost(response, limits)
        if expected_substring not in response.output:
            return _observation(
                disposition=CanaryDisposition.SUBJECT_FAILURE,
                attempts=attempt,
                response=response,
                cost=cost,
                reason="valid provider response violated the predeclared canary assertion",
            )
        return _observation(
            disposition=CanaryDisposition.OBSERVED,
            attempts=attempt,
            response=response,
            cost=cost,
            reason="live provider observation satisfied the predeclared canary assertion",
        )

    return _uncertain(limits.max_attempts, last_response, "canary ended without observation")


def _validate_response(
    response: ProviderCanaryResponse,
    limits: ProviderCanaryLimits,
) -> str | None:
    if type(response.status_code) is not int or not 100 <= response.status_code <= 599:
        return "provider response status is invalid"
    if response.output is not None and type(response.output) is not str:
        return "provider output is not exact text"
    for name in ("request_id", "model_revision"):
        value = getattr(response, name)
        if value is not None and (type(value) is not str or not value or len(value) > 256):
            return f"provider {name} metadata is invalid"
    for name in ("input_tokens", "output_tokens"):
        value = getattr(response, name)
        if type(value) is not int or value < 0:
            return f"provider {name} telemetry is invalid"
    if response.input_tokens > limits.max_input_tokens:
        return "provider input token usage exceeded the configured ceiling"
    if response.output_tokens > limits.max_output_tokens:
        return "provider output token usage exceeded the configured ceiling"
    if response.retry_after_seconds is not None:
        value = response.retry_after_seconds
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return "provider retry-after metadata is invalid"
        if not math.isfinite(float(value)) or float(value) < 0.0:
            return "provider retry-after metadata is invalid"
    if _estimated_cost(response, limits) > limits.max_estimated_cost_usd:
        return "observed estimated cost exceeded the configured ceiling"
    return None


def _estimated_cost(
    response: ProviderCanaryResponse,
    limits: ProviderCanaryLimits,
) -> float:
    return (
        response.input_tokens * limits.input_usd_per_million
        + response.output_tokens * limits.output_usd_per_million
    ) / 1_000_000.0


def _sleep_within_wall(
    seconds: float,
    *,
    started: float,
    limits: ProviderCanaryLimits,
    clock: Clock,
    sleep: Sleeper,
) -> bool:
    remaining = limits.wall_clock_seconds - (clock() - started)
    if seconds >= remaining:
        return False
    sleep(seconds)
    return clock() - started < limits.wall_clock_seconds


def _uncertain(
    attempts: int,
    response: ProviderCanaryResponse | None,
    reason: str,
) -> ProviderCanaryObservation:
    return ProviderCanaryObservation(
        schema_version="agent-evals/live-provider-canary/v1",
        disposition=CanaryDisposition.PROVIDER_UNCERTAIN,
        attempts=attempts,
        provider_request_id=None if response is None else response.request_id,
        provider_model_revision=None if response is None else response.model_revision,
        input_tokens=0 if response is None else response.input_tokens,
        output_tokens=0 if response is None else response.output_tokens,
        estimated_cost_usd=0.0,
        reason=reason,
    )


def _observation(
    *,
    disposition: CanaryDisposition,
    attempts: int,
    response: ProviderCanaryResponse,
    cost: float,
    reason: str,
) -> ProviderCanaryObservation:
    return ProviderCanaryObservation(
        schema_version="agent-evals/live-provider-canary/v1",
        disposition=disposition,
        attempts=attempts,
        provider_request_id=response.request_id,
        provider_model_revision=response.model_revision,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        estimated_cost_usd=cost,
        reason=reason,
    )
