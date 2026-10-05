from __future__ import annotations

import pytest

from agent_evals.live_provider import (
    CanaryDisposition,
    ProviderCanaryLimits,
    ProviderCanaryResponse,
    run_provider_canary,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _limits(**overrides: object) -> ProviderCanaryLimits:
    values: dict[str, object] = {
        "max_attempts": 3,
        "request_timeout_seconds": 5.0,
        "wall_clock_seconds": 30.0,
        "max_requests_per_minute": 6,
        "max_input_tokens": 100,
        "max_output_tokens": 20,
        "input_usd_per_million": 1.0,
        "output_usd_per_million": 2.0,
        "max_estimated_cost_usd": 0.001,
    }
    values.update(overrides)
    return ProviderCanaryLimits(**values)  # type: ignore[arg-type]


def test_successful_live_observation_retains_request_and_model_metadata() -> None:
    observation = run_provider_canary(
        lambda timeout: ProviderCanaryResponse(
            status_code=200,
            output="CANARY_OK",
            request_id="req_live_1",
            model_revision="model-rev-7",
            input_tokens=10,
            output_tokens=2,
        ),
        expected_substring="CANARY_OK",
        limits=_limits(),
    )

    assert observation.disposition is CanaryDisposition.OBSERVED
    assert observation.provider_request_id == "req_live_1"
    assert observation.provider_model_revision == "model-rev-7"
    assert observation.estimated_cost_usd == pytest.approx(0.000014)
    assert observation.historical_observation is True
    assert observation.provider_attestation is False


def test_valid_response_that_breaks_assertion_is_subject_failure() -> None:
    observation = run_provider_canary(
        lambda timeout: ProviderCanaryResponse(
            status_code=200,
            output="WRONG",
            input_tokens=4,
            output_tokens=1,
        ),
        expected_substring="CANARY_OK",
        limits=_limits(),
    )

    assert observation.disposition is CanaryDisposition.SUBJECT_FAILURE
    assert "violated" in observation.reason


def test_429_is_retried_under_rate_ceiling_then_can_succeed() -> None:
    clock = _Clock()
    responses = iter(
        (
            ProviderCanaryResponse(status_code=429, retry_after_seconds=1.0),
            ProviderCanaryResponse(status_code=200, output="CANARY_OK"),
        )
    )

    observation = run_provider_canary(
        lambda timeout: next(responses),
        expected_substring="CANARY_OK",
        limits=_limits(),
        clock=clock,
        sleep=clock.sleep,
    )

    assert observation.disposition is CanaryDisposition.OBSERVED
    assert observation.attempts == 2
    assert clock.value == 10.0


def test_5xx_exhaustion_is_provider_uncertainty_not_subject_failure() -> None:
    clock = _Clock()
    observation = run_provider_canary(
        lambda timeout: ProviderCanaryResponse(status_code=503),
        expected_substring="CANARY_OK",
        limits=_limits(wall_clock_seconds=40.0),
        clock=clock,
        sleep=clock.sleep,
    )

    assert observation.disposition is CanaryDisposition.PROVIDER_UNCERTAIN
    assert observation.attempts == 3
    assert "exhausted" in observation.reason


def test_timeout_exhaustion_is_provider_uncertainty() -> None:
    clock = _Clock()

    def timeout_transport(timeout: float) -> ProviderCanaryResponse:
        raise TimeoutError

    observation = run_provider_canary(
        timeout_transport,
        expected_substring="CANARY_OK",
        limits=_limits(wall_clock_seconds=40.0),
        clock=clock,
        sleep=clock.sleep,
    )

    assert observation.disposition is CanaryDisposition.PROVIDER_UNCERTAIN
    assert "timed out" in observation.reason


def test_usage_above_declared_ceiling_is_provider_uncertainty() -> None:
    observation = run_provider_canary(
        lambda timeout: ProviderCanaryResponse(
            status_code=200,
            output="CANARY_OK",
            input_tokens=101,
        ),
        expected_substring="CANARY_OK",
        limits=_limits(),
    )

    assert observation.disposition is CanaryDisposition.PROVIDER_UNCERTAIN
    assert "token usage exceeded" in observation.reason


def test_cost_ceiling_rejects_unsafe_configuration_before_any_request() -> None:
    with pytest.raises(ValueError, match="cost ceiling"):
        _limits(
            max_input_tokens=1000,
            max_output_tokens=1000,
            input_usd_per_million=100.0,
            output_usd_per_million=100.0,
            max_estimated_cost_usd=0.01,
        )


def test_canonical_observation_explicitly_denies_provider_attestation() -> None:
    observation = run_provider_canary(
        lambda timeout: ProviderCanaryResponse(status_code=200, output="CANARY_OK"),
        expected_substring="CANARY_OK",
        limits=_limits(),
    )

    payload = observation.canonical_json()
    assert '"historical_observation":true' in payload
    assert '"provider_attestation":false' in payload
