from __future__ import annotations

import pytest

from agent_evals.statistics.limits import validate_reliability_k


def test_reliability_k_accepts_exact_minimum() -> None:
    assert validate_reliability_k(1) == 1


def test_reliability_k_rejects_zero_with_stable_reason() -> None:
    with pytest.raises(ValueError, match=r"^k must be an integer >= 1$"):
        validate_reliability_k(0)


def test_reliability_k_rejects_bool_even_when_truthy() -> None:
    with pytest.raises(ValueError, match=r"^k must be an integer >= 1$"):
        validate_reliability_k(True)
