from __future__ import annotations

import pytest

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.drift import detect_binary_change_point
from agent_evals.statistics.sequential import bernoulli_confidence_sequence


def test_confidence_sequence_keeps_unresolved_attempts_out_of_binary_time() -> None:
    points = bernoulli_confidence_sequence(
        (
            TrialVerdict.PASS,
            TrialVerdict.BLOCKED,
            TrialVerdict.INCONCLUSIVE,
            TrialVerdict.PASS,
        ),
        alpha=0.05,
    )

    first, blocked, inconclusive, second_pass = points
    assert first.resolved_index == 1
    assert blocked.resolved_index == 1
    assert inconclusive.resolved_index == 1
    assert blocked.lower == first.lower
    assert blocked.upper == first.upper
    assert blocked.allocated_alpha == 0.0
    assert inconclusive.allocated_alpha == 0.0
    assert second_pass.resolved_index == 2
    assert second_pass.allocated_alpha > 0.0
    assert second_pass.blocked == 1
    assert second_pass.inconclusive == 1


def test_confidence_sequence_tightens_for_consistent_successes() -> None:
    points = bernoulli_confidence_sequence(
        tuple(TrialVerdict.PASS for _ in range(500)),
        alpha=0.05,
    )

    assert points[-1].lower > 0.80
    assert points[-1].upper == 1.0


def test_change_point_detects_large_corrected_rate_shift() -> None:
    verdicts = (
        tuple(TrialVerdict.PASS for _ in range(45))
        + tuple(TrialVerdict.FAIL for _ in range(5))
        + tuple(TrialVerdict.PASS for _ in range(5))
        + tuple(TrialVerdict.FAIL for _ in range(45))
    )

    result = detect_binary_change_point(
        verdicts,
        minimum_segment_trials=20,
        alpha=0.05,
        minimum_absolute_delta=0.20,
    )

    assert result.detected is True
    assert result.candidate is not None
    assert result.candidate.delta < -0.70
    assert result.candidate.adjusted_p_upper_bound <= 0.05


def test_change_point_does_not_claim_stationary_noise_shift() -> None:
    verdicts = tuple(
        TrialVerdict.PASS if index % 2 == 0 else TrialVerdict.FAIL
        for index in range(100)
    )

    result = detect_binary_change_point(
        verdicts,
        minimum_segment_trials=20,
        alpha=0.05,
        minimum_absolute_delta=0.20,
    )

    assert result.detected is False
    assert result.candidate is None


def test_change_point_refuses_unresolved_attempts() -> None:
    verdicts = (
        tuple(TrialVerdict.PASS for _ in range(20))
        + (TrialVerdict.BLOCKED,)
        + tuple(TrialVerdict.FAIL for _ in range(20))
    )

    with pytest.raises(ValueError, match="BLOCKED and INCONCLUSIVE"):
        detect_binary_change_point(
            verdicts,
            minimum_segment_trials=20,
        )


def test_change_point_requires_two_bounded_segments() -> None:
    with pytest.raises(ValueError, match="two complete"):
        detect_binary_change_point(
            tuple(TrialVerdict.PASS for _ in range(30)),
            minimum_segment_trials=20,
        )
